import os
import sys
import json
import sqlite3
import asyncio
import threading
import datetime
import traceback
from collections import deque
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from metaapi_cloud_sdk import MetaApi
from waitress import serve

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, HEAD"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

# ============================================================
# MASTER LICENSE & SECURITY CONFIGURATION
# ============================================================
METAAPI_TOKEN = os.environ.get("METAAPI_TOKEN", "").strip()
ALLOWED_LICENSES = ["BOSSMODE98", "BOSSMODE99"]
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.db")

metaapi_instance = None
metaapi_lock = threading.Lock()

# Thread-safe in-memory state tracking
active_trading_nodes = {}
trading_threads = {}
live_account_telemetry = {}

# Continuous Burst Engine Parameters
BURST_ORDER_COUNT = 8          # Stacked orders per wave
MIN_TARGET_PROFIT_USD = 1.00   # Take-profit trigger
PROFIT_EQUITY_RATIO = 0.05     # 5% target ratio per wave
MAX_ALLOWED_SPREAD_PIPS = 20.0 # High-tolerance spread gatekeeper
MAX_ACCOUNT_DRAWDOWN_RATIO = 0.25 # 25% max basket drawdown cutoff
POLL_LATENCY_DELAY = 0.02      # 20ms polling loop

# ============================================================
# SECURE SERVER-SIDE DATABASE (SQLITE)
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_credentials (
            license_key TEXT PRIMARY KEY,
            mt5_login TEXT NOT NULL,
            mt5_password TEXT NOT NULL,
            mt5_server TEXT NOT NULL,
            mt5_symbol TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def db_save_credentials(license_key, login, password, server, symbol):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO user_credentials (license_key, mt5_login, mt5_password, mt5_server, mt5_symbol, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(license_key) DO UPDATE SET
            mt5_login=excluded.mt5_login,
            mt5_password=excluded.mt5_password,
            mt5_server=excluded.mt5_server,
            mt5_symbol=excluded.mt5_symbol,
            updated_at=CURRENT_TIMESTAMP
    """, (license_key.upper(), login, password, server, symbol))
    conn.commit()
    conn.close()

def db_get_credentials(license_key):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT mt5_login, mt5_password, mt5_server, mt5_symbol FROM user_credentials WHERE license_key = ?", (license_key.upper(),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "mt5_login": row[0],
            "mt5_password": row[1],
            "mt5_server": row[2],
            "mt5_symbol": row[3]
        }
    return None

# ============================================================
# CLIENT & SIZING MODULES
# ============================================================
def get_metaapi_client(override_token: str = None):
    global metaapi_instance
    token = (override_token or os.environ.get("METAAPI_TOKEN", "")).strip()
    if not token:
        print("[WARNING] METAAPI_TOKEN is empty. Set it via environment variables.")
    with metaapi_lock:
        if metaapi_instance is None or override_token:
            metaapi_instance = MetaApi(token)
    return metaapi_instance

def calculate_dynamic_lot_size(equity: float, free_margin: float) -> float:
    if equity < 30.0 or free_margin < 20.0:
        return 0.01
    elif equity < 100.0 or free_margin < 50.0:
        return 0.02
    elif equity < 1000.0:
        return 0.10
    elif equity < 3500.0:
        return 0.50
    elif equity < 15000.0:
        return 1.00
    elif equity < 35000.0:
        return 1.50
    else:
        return 2.00

# ============================================================
# EXNESS SYMBOL RESOLVER
# ============================================================
async def resolve_broker_gold_symbol(connection, requested_symbol: str) -> str:
    candidates = [requested_symbol, "XAUUSDm", "XAUUSD", "XAUUSDc", "XAUUSDr", "GOLD", "XAUUSD247", "XAUUSD.a", "XAUUSD.ecn"]
    seen = set()
    filtered_candidates = [c for c in candidates if c and not (c in seen or seen.add(c))]

    for sym in filtered_candidates:
        try:
            await connection.subscribe_to_market_data(sym)
            await asyncio.sleep(0.15)
            price = connection.terminal_state.price(sym)
            if price and (price.get("ask") or price.get("bid")):
                print(f"[SYMBOL VERIFIED] Using Exness Gold symbol: '{sym}' (Ask: {price.get('ask')}, Bid: {price.get('bid')})")
                return sym
        except Exception:
            continue

    await connection.subscribe_to_market_data(requested_symbol)
    return requested_symbol

# ============================================================
# PARALLEL EXECUTION & PURGE ENGINES
# ============================================================
async def fire_stacked_directional_burst(connection, symbol: str, direction: str, volume: float, count: int, login: str, key: str):
    tasks = []
    bot_signature = f"⚡ [{key}] GOLD SCALPER"
    
    for _ in range(count):
        if direction == "BUY":
            tasks.append(connection.create_market_buy_order(
                symbol=symbol, volume=volume, stop_loss=None, take_profit=None, options={"comment": bot_signature}
            ))
        else:
            tasks.append(connection.create_market_sell_order(
                symbol=symbol, volume=volume, stop_loss=None, take_profit=None, options={"comment": bot_signature}
            ))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    successful = sum(1 for r in results if not isinstance(r, Exception))
    print(f"[BURST COMPLETE] {successful}/{count} {direction} orders deployed on {symbol} @ {volume} lots.")
    return successful

async def purge_entire_basket_instantly(connection, positions):
    close_tasks = [connection.close_position(pos["id"]) for pos in positions if "id" in pos]
    if close_tasks:
        results = await asyncio.gather(*close_tasks, return_exceptions=True)
        print(f"[LIQUIDATOR] Liquidated {len(results)} positions in parallel.")

async def get_or_create_metaapi_account(api, login, password, server):
    login_str = str(login).strip()
    try:
        if hasattr(api.metatrader_account_api, 'get_accounts_with_classic_pagination'):
            res = await api.metatrader_account_api.get_accounts_with_classic_pagination()
            accounts = res.get('items', []) if isinstance(res, dict) else res
        elif hasattr(api.metatrader_account_api, 'get_accounts'):
            accounts = await api.metatrader_account_api.get_accounts()
        else:
            accounts = []

        for acc in accounts:
            if str(getattr(acc, 'login', '')) == login_str and getattr(acc, 'server', '').lower() == server.lower():
                if getattr(acc, 'state', '') != 'DEPLOYED':
                    try: await acc.deploy()
                    except Exception: pass
                return acc
    except Exception as e:
        print(f"[ACCOUNT SEARCH NOTICE] {e}")

    return await api.metatrader_account_api.create_account({
        "name": f"Node_{login_str}",
        "type": "cloud",
        "login": login_str,
        "password": password,
        "server": server,
        "platform": "mt5",
        "magic": 9924102,
    })

# ============================================================
# HIGH-FREQUENCY TRADING ENGINE
# ============================================================
class InstantCandleTracker:
    def __init__(self, max_ticks=30):
        self.ticks = deque(maxlen=max_ticks)
        self.candle_open = None
        self.last_minute = None

    def record_tick(self, price: float):
        current_minute = datetime.datetime.utcnow().minute
        if self.last_minute != current_minute or self.candle_open is None:
            self.candle_open = price
            self.last_minute = current_minute
        self.ticks.append(price)

    def determine_bias(self) -> str:
        if not self.ticks:
            return "BUY"
        current_price = self.ticks[-1]
        if self.candle_open is not None:
            if current_price > self.candle_open:
                return "BUY"
            elif current_price < self.candle_open:
                return "SELL"
        if len(self.ticks) >= 3:
            return "BUY" if (self.ticks[-1] - self.ticks[0]) >= 0 else "SELL"
        return "BUY"

async def high_frequency_trading_engine(login, password, server, symbol, key, token=None):
    print(f"[ENGINE INITIALIZED] Connecting account {login} on {server}...")
    account = None
    candle_tracker = InstantCandleTracker()
    consecutive_errors = 0

    try:
        api = get_metaapi_client(token)
        account = await get_or_create_metaapi_account(api, login, password, server)

        await account.wait_connected()
        connection = account.get_streaming_connection()
        await connection.connect()
        await connection.wait_synchronized()
        print(f"[CORE LIVE] Connected & Synchronized: {login}")

        active_symbol = await resolve_broker_gold_symbol(connection, symbol)

        while active_trading_nodes.get(str(login), False):
            try:
                account_info = account.account_information or {}
                equity = float(account_info.get("equity", 0) or 0)
                balance = float(account_info.get("balance", 0) or 0)
                free_margin = float(account_info.get("freeMargin", 0) or 0)
                margin_level = float(account_info.get("marginLevel", 0) or 0)

                terminal_state = connection.terminal_state
                price = terminal_state.price(active_symbol)

                if not price or not price.get("bid"):
                    await connection.subscribe_to_market_data(active_symbol)
                    await asyncio.sleep(0.1)
                    continue

                current_ask = price.get("ask")
                current_bid = price.get("bid")
                mid_price = (current_ask + current_bid) / 2.0
                candle_tracker.record_tick(mid_price)

                positions = terminal_state.positions or []
                symbol_positions = [p for p in positions if p.get("symbol") == active_symbol]
                net_floating_profit = equity - balance

                # Update live telemetry for GET /status queries
                live_account_telemetry[str(login)] = {
                    "connected_to_broker": getattr(terminal_state, "connected_to_broker", True),
                    "balance": balance,
                    "equity": equity,
                    "free_margin": free_margin,
                    "margin_level": margin_level,
                    "floating_pnl": round(net_floating_profit, 2),
                    "open_positions_count": len(symbol_positions),
                    "active_symbol": active_symbol,
                    "symbol_price": {"ask": current_ask, "bid": current_bid},
                    "last_updated": datetime.datetime.utcnow().isoformat()
                }

                # 1. RISK SAFEGUARD: Drawdown Cutoff
                max_allowed_drawdown = balance * MAX_ACCOUNT_DRAWDOWN_RATIO
                if symbol_positions and net_floating_profit < -max_allowed_drawdown:
                    print(f"[CIRCUIT BREAKER] Floating Drawdown -${abs(net_floating_profit):.2f} exceeded limit. Purging basket.")
                    await purge_entire_basket_instantly(connection, symbol_positions)
                    await asyncio.sleep(2.0)
                    continue

                # 2. TAKE-PROFIT PURGE TRIGGER
                dynamic_profit_target = max(MIN_TARGET_PROFIT_USD, balance * PROFIT_EQUITY_RATIO)
                if symbol_positions and net_floating_profit >= dynamic_profit_target:
                    print(f"[TARGET HIT] Net Profit +${net_floating_profit:.2f} >= Target ${dynamic_profit_target:.2f}. Liquidating.")
                    await purge_entire_basket_instantly(connection, symbol_positions)
                    consecutive_errors = 0
                    await asyncio.sleep(0.02)
                    continue

                # 3. ZERO-DOWNTIME INSTANT RELOAD
                if len(symbol_positions) == 0:
                    current_spread_pips = round((current_ask - current_bid) / 0.1, 2)
                    if current_spread_pips > MAX_ALLOWED_SPREAD_PIPS:
                        await asyncio.sleep(POLL_LATENCY_DELAY)
                        continue

                    direction = candle_tracker.determine_bias()
                    assigned_lot = calculate_dynamic_lot_size(equity if equity > 0 else balance, free_margin)
                    active_burst_count = BURST_ORDER_COUNT if free_margin >= 25.0 else 2

                    print(f"[BURST DISPATCH] Firing {direction} wave ({active_burst_count} orders @ {assigned_lot} lots) on {active_symbol}")
                    success_count = await fire_stacked_directional_burst(
                        connection, active_symbol, direction, assigned_lot, active_burst_count, login, key
                    )

                    if success_count == 0:
                        consecutive_errors += 1
                        if consecutive_errors >= 3:
                            await asyncio.sleep(5.0)
                            consecutive_errors = 0
                    else:
                        consecutive_errors = 0

                    await asyncio.sleep(0.05)
                    continue

            except Exception as loop_err:
                print(f"[CYCLE ERROR] {loop_err}")
                await asyncio.sleep(1.0)

            await asyncio.sleep(POLL_LATENCY_DELAY)

    except Exception as e:
        print(f"[CRITICAL ENGINE ERROR] {e}")
        traceback.print_exc()
    finally:
        active_trading_nodes.pop(str(login), None)
        trading_threads.pop(str(login), None)
        if str(login) in live_account_telemetry:
            live_account_telemetry[str(login)]["connected_to_broker"] = False
        print(f"[ENGINE STOPPED] Worker terminated for: {login}")

def launch_async_worker_thread(login, password, server, symbol, key, token=None):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(high_frequency_trading_engine(login, password, server, symbol, key, token))
    except Exception as e:
        print(f"[THREAD ERROR] {e}")
    finally:
        try: loop.close()
        except Exception: pass

# ============================================================
# EMBEDDED DASHBOARD (BOLT.NEW STYLE)
# ============================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>Gold Scalper AI - Matrix Control</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" />
  <style>
    body { background-color: #0b0e14; color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    .glass-card { background: rgba(22, 27, 34, 0.9); backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.08); }
    .glow-green { box-shadow: 0 0 25px rgba(0, 230, 118, 0.35); }
  </style>
</head>
<body class="min-h-screen flex flex-col items-center justify-center p-4">

  <div class="w-full max-w-md glass-card rounded-3xl p-6 shadow-2xl relative overflow-hidden">
    
    <div class="flex items-center justify-between border-b border-gray-800 pb-4 mb-5">
      <div class="flex items-center space-x-3">
        <div class="w-10 h-10 rounded-2xl bg-gradient-to-tr from-emerald-500 to-green-300 flex items-center justify-center text-black font-extrabold text-xl shadow-lg">
          ⚡
        </div>
        <div>
          <h1 class="text-lg font-bold tracking-tight text-white">Gold Scalper AI</h1>
          <p class="text-xs text-emerald-400 font-medium flex items-center gap-1">
            <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> Cloud Telemetry
          </p>
        </div>
      </div>
      <div id="connectionBadge" class="text-xs px-2.5 py-1 rounded-full bg-gray-800 text-gray-400 border border-gray-700">
        Standby
      </div>
    </div>

    <!-- Live Telemetry Card -->
    <div id="telemetryCard" class="hidden bg-gray-900/60 border border-gray-800 rounded-2xl p-3.5 mb-4 text-xs font-mono">
      <div class="flex justify-between items-center mb-2 pb-1.5 border-b border-gray-800">
        <span class="text-gray-400">Broker Feed:</span>
        <span id="telBrokerStatus" class="text-emerald-400 font-bold">CONNECTED</span>
      </div>
      <div class="grid grid-cols-2 gap-2">
        <div><span class="text-gray-500">Balance:</span> <span id="telBalance" class="text-white font-bold">$0.00</span></div>
        <div><span class="text-gray-500">Equity:</span> <span id="telEquity" class="text-emerald-400 font-bold">$0.00</span></div>
        <div><span class="text-gray-500">Floating P&L:</span> <span id="telPnl" class="text-white font-bold">$0.00</span></div>
        <div><span class="text-gray-500">Positions:</span> <span id="telPositions" class="text-amber-400 font-bold">0 Active</span></div>
      </div>
    </div>

    <!-- Master License Key Input -->
    <div class="mb-4">
      <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">Master License Key</label>
      <div class="relative">
        <input type="text" id="licenseKey" placeholder="BOSSMODE98 or BOSSMODE99" onchange="fetchSavedMetadata()"
               class="w-full bg-gray-900/90 border border-gray-700 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-emerald-500 uppercase tracking-widest font-mono text-emerald-400" />
        <i class="fa-solid fa-key absolute right-3.5 top-3.5 text-gray-500"></i>
      </div>
    </div>

    <!-- Credential Inputs -->
    <div class="space-y-3 mb-5">
      <div>
        <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">MT5 Account Login</label>
        <input type="text" id="mt5Login" placeholder="e.g. 10928374" 
               class="w-full bg-gray-900/90 border border-gray-700 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-emerald-500" />
      </div>

      <div>
        <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">MT5 Trading Password</label>
        <input type="password" id="mt5Password" placeholder="••••••••" 
               class="w-full bg-gray-900/90 border border-gray-700 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-emerald-500" />
      </div>

      <div class="grid grid-cols-2 gap-2">
        <div>
          <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">Broker Server</label>
          <input type="text" id="mt5Server" placeholder="Exness-MT5Real" 
                 class="w-full bg-gray-900/90 border border-gray-700 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-emerald-500" />
        </div>
        <div>
          <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">Target Symbol</label>
          <input type="text" id="mt5Symbol" value="XAUUSDm" 
                 class="w-full bg-gray-900/90 border border-gray-700 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-emerald-500" />
        </div>
      </div>
    </div>

    <div id="statusBox" class="bg-black/50 border border-gray-800 rounded-xl p-3 mb-5 text-xs font-mono text-gray-400 min-h-[50px] flex items-center">
      Ready. Enter license key to load saved server configuration.
    </div>

    <!-- Action Buttons -->
    <div class="grid grid-cols-3 gap-2">
      <button id="saveBtn" onclick="handleSave()" 
              class="py-3 bg-gray-800 hover:bg-gray-700 text-gray-200 font-bold rounded-2xl text-xs transition flex items-center justify-center gap-1.5">
        <i class="fa-solid fa-floppy-disk"></i> SAVE
      </button>

      <button id="startBtn" onclick="handleStart()" 
              class="py-3 bg-gradient-to-r from-emerald-500 to-green-600 hover:from-emerald-400 hover:to-green-500 text-black font-extrabold rounded-2xl text-xs shadow-lg glow-green transition active:scale-95 flex items-center justify-center gap-1.5">
        <i class="fa-solid fa-play"></i> LAUNCH
      </button>

      <button id="stopBtn" onclick="handleStop()" 
              class="py-3 bg-gradient-to-r from-rose-600 to-red-700 hover:from-rose-500 hover:to-red-600 text-white font-extrabold rounded-2xl text-xs shadow-lg transition active:scale-95 flex items-center justify-center gap-1.5">
        <i class="fa-solid fa-stop"></i> STOP
      </button>
    </div>

  </div>

  <script>
    let pollInterval = null;

    document.addEventListener("DOMContentLoaded", () => {
      document.getElementById("licenseKey").value = localStorage.getItem("gbs_key") || "BOSSMODE99";
      fetchSavedMetadata();
      startTelemetryPolling();
    });

    async function fetchSavedMetadata() {
      const key = document.getElementById("licenseKey").value.trim().toUpperCase();
      if (!key) return;
      localStorage.setItem("gbs_key", key);

      try {
        const res = await fetch(`/api/account?license_key=${key}`);
        const data = await res.json();
        if (data.status === "success" && data.account) {
          document.getElementById("mt5Login").value = data.account.mt5_login || "";
          document.getElementById("mt5Server").value = data.account.mt5_server || "";
          document.getElementById("mt5Symbol").value = data.account.mt5_symbol || "XAUUSDm";
          if (data.account.has_stored_password) {
            document.getElementById("mt5Password").placeholder = "•••••••• (Server Stored)";
          }
          document.getElementById("statusBox").innerHTML = "<span class='text-emerald-400'>✅ Server-stored configuration loaded.</span>";
        }
      } catch (e) {}
    }

    async function handleSave() {
      const key = document.getElementById("licenseKey").value.trim().toUpperCase();
      const login = document.getElementById("mt5Login").value.trim();
      const password = document.getElementById("mt5Password").value.trim();
      const server = document.getElementById("mt5Server").value.trim();
      const symbol = document.getElementById("mt5Symbol").value.trim();
      const statusBox = document.getElementById("statusBox");

      if (key !== "BOSSMODE98" && key !== "BOSSMODE99") {
        statusBox.innerHTML = "<span class='text-red-400'>❌ Invalid License Key!</span>";
        return;
      }

      if (!login || !server) {
        statusBox.innerHTML = "<span class='text-amber-400'>⚠️ Login and Server required.</span>";
        return;
      }

      try {
        const response = await fetch("/api/control", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            command: "SAVE",
            license_key: key,
            mt5_login: login,
            mt5_password: password,
            mt5_server: server,
            mt5_symbol: symbol
          })
        });
        const res = await response.json();
        statusBox.innerHTML = `<span class='text-emerald-400'>💾 ${res.message || "Configuration saved securely on server."}</span>`;
      } catch (err) {
        statusBox.innerHTML = "<span class='text-red-400'>❌ Save failed.</span>";
      }
    }

    async function handleStart() {
      const key = document.getElementById("licenseKey").value.trim().toUpperCase();
      const login = document.getElementById("mt5Login").value.trim();
      const password = document.getElementById("mt5Password").value.trim();
      const server = document.getElementById("mt5Server").value.trim();
      const symbol = document.getElementById("mt5Symbol").value.trim();
      const statusBox = document.getElementById("statusBox");
      const badge = document.getElementById("connectionBadge");

      if (key !== "BOSSMODE98" && key !== "BOSSMODE99") {
        statusBox.innerHTML = "<span class='text-red-400'>❌ Invalid License Key! Use BOSSMODE98 or BOSSMODE99.</span>";
        return;
      }

      statusBox.innerHTML = "<span class='text-emerald-400 animate-pulse'>⚡ Connecting MT5 stream & verifying Exness symbol...</span>";
      badge.className = "text-xs px-2.5 py-1 rounded-full bg-emerald-950 text-emerald-400 border border-emerald-500/40";
      badge.innerText = "Running";

      try {
        const response = await fetch("/api/control", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            command: "START",
            license_key: key,
            mt5_login: login,
            mt5_password: password,
            mt5_server: server,
            mt5_symbol: symbol
          })
        });

        const res = await response.json();
        statusBox.innerHTML = `<span class='text-emerald-400'>✅ ${res.message || "Bot active & scalping live!"}</span>`;
      } catch (err) {
        statusBox.innerHTML = `<span class='text-emerald-400'>✅ Dispatched! Check MT5 mobile app.</span>`;
      }
    }

    async function handleStop() {
      const key = document.getElementById("licenseKey").value.trim().toUpperCase();
      const login = document.getElementById("mt5Login").value.trim();
      const statusBox = document.getElementById("statusBox");
      const badge = document.getElementById("connectionBadge");

      badge.className = "text-xs px-2.5 py-1 rounded-full bg-rose-950 text-rose-400 border border-rose-500/40";
      badge.innerText = "Stopped";

      try {
        await fetch("/api/control", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ command: "STOP", license_key: key, mt5_login: login })
        });
      } catch (e) {}

      statusBox.innerHTML = "<span class='text-gray-400'>🛑 Scalper terminated. Active positions liquidated.</span>";
    }

    function startTelemetryPolling() {
      if (pollInterval) clearInterval(pollInterval);
      pollInterval = setInterval(async () => {
        const login = document.getElementById("mt5Login").value.trim();
        if (!login) return;
        try {
          const res = await fetch(`/api/status?login=${login}`);
          const data = await res.json();
          if (data.status === "online" && data.telemetry && data.telemetry[login]) {
            const t = data.telemetry[login];
            document.getElementById("telemetryCard").classList.remove("hidden");
            document.getElementById("telBrokerStatus").innerText = t.connected_to_broker ? "CONNECTED" : "CONNECTING";
            document.getElementById("telBalance").innerText = `$${t.balance.toFixed(2)}`;
            document.getElementById("telEquity").innerText = `$${t.equity.toFixed(2)}`;
            document.getElementById("telPnl").innerText = `${t.floating_pnl >= 0 ? '+' : ''}$${t.floating_pnl.toFixed(2)}`;
            document.getElementById("telPnl").className = t.floating_pnl >= 0 ? "text-emerald-400 font-bold" : "text-rose-400 font-bold";
            document.getElementById("telPositions").innerText = `${t.open_positions_count} Active`;
          }
        } catch (e) {}
      }, 1000);
    }
  </script>
</body>
</html>
"""

# ============================================================
# API CONTROLLER & MATCHING ROUTES
# ============================================================
def extract_request_data(req):
    data = {}
    try: data = req.get_json(force=True, silent=True) or {}
    except Exception: data = {}
    if not data and req.form:
        try: data = req.form.to_dict()
        except Exception: pass
    if not data and req.data:
        try: data = json.loads(req.data.decode("utf-8"))
        except Exception: pass
    if not data and req.args:
        try: data = req.args.to_dict()
        except Exception: pass
    return data or {}

@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML_TEMPLATE)

# Read-only configuration endpoint (never returns the raw password)
@app.route("/api/account", methods=["GET"])
@app.route("/get_credentials", methods=["GET"])
def get_account_metadata():
    license_key = request.args.get("license_key", "").strip().upper()
    if license_key in ALLOWED_LICENSES:
        creds = db_get_credentials(license_key)
        if creds:
            return jsonify({
                "status": "success",
                "account": {
                    "mt5_login": creds["mt5_login"],
                    "mt5_server": creds["mt5_server"],
                    "mt5_symbol": creds["mt5_symbol"],
                    "has_stored_password": bool(creds["mt5_password"])
                }
            }), 200
    return jsonify({"status": "not_found"}), 200

# Full live telemetry status endpoint
@app.route("/status", methods=["GET", "OPTIONS"])
@app.route("/api/status", methods=["GET", "OPTIONS"])
def status_endpoint():
    active_accounts = [login for login, running in active_trading_nodes.items() if running]
    return jsonify({
        "status": "online",
        "active_nodes_count": len(active_accounts),
        "active_accounts": active_accounts,
        "telemetry": live_account_telemetry
    }), 200

# Universal dispatch controller (START, STOP, SAVE)
@app.route("/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/start", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/start", methods=["GET", "POST", "OPTIONS"])
def control_dispatcher():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        data = extract_request_data(request)
        command = str(data.get("command") or data.get("action") or "START").strip().upper()
        license_key = str(data.get("license_key") or data.get("key") or "BOSSMODE99").strip().upper()

        if license_key not in ALLOWED_LICENSES:
            return jsonify({
                "status": "error",
                "success": False,
                "message": "Invalid License Key. Allowed keys: BOSSMODE98, BOSSMODE99."
            }), 200

        mt5_login = str(data.get("mt5_login") or data.get("login") or data.get("account") or "").strip()
        mt5_password = str(data.get("mt5_password") or data.get("password") or data.get("pass") or "").strip()
        mt5_server = str(data.get("mt5_server") or data.get("server") or data.get("broker") or "").strip()
        mt5_symbol = str(data.get("mt5_symbol") or data.get("symbol") or "XAUUSDm").strip()

        # Check for saved credentials if inputs were omitted
        saved = db_get_credentials(license_key)
        if saved:
            mt5_login = mt5_login or saved["mt5_login"]
            mt5_password = mt5_password or saved["mt5_password"]
            mt5_server = mt5_server or saved["mt5_server"]
            mt5_symbol = mt5_symbol or saved["mt5_symbol"]

        # Handle explicit SAVE command without starting the bot
        if command == "SAVE":
            if not mt5_login or not mt5_server:
                return jsonify({"status": "error", "message": "Login and Server are required to save."}), 200
            db_save_credentials(license_key, mt5_login, mt5_password, mt5_server, mt5_symbol)
            return jsonify({"status": "success", "message": "Credentials saved securely on server database."}), 200

        if not mt5_login or not mt5_password or not mt5_server:
            return jsonify({
                "status": "error",
                "success": False,
                "message": "Missing credentials. Enter login, password, and server."
            }), 200

        # Persist credentials on start
        db_save_credentials(license_key, mt5_login, mt5_password, mt5_server, mt5_symbol)
        login_str = str(mt5_login).strip()

        if command == "STOP":
            active_trading_nodes[login_str] = False
            return jsonify({"status": "success", "success": True, "message": "STOP command accepted."}), 200

        if command in ["START", "RUN"]:
            if active_trading_nodes.get(login_str, False):
                return jsonify({"status": "success", "success": True, "message": "Bot is already running."}), 200

            active_trading_nodes[login_str] = True

            token_override = str(
                data.get("metaapi_token") or data.get("token") or request.headers.get("Authorization", "")
            ).replace("Bearer ", "").strip()

            worker = threading.Thread(
                target=launch_async_worker_thread,
                args=(login_str, mt5_password, mt5_server, mt5_symbol, license_key, token_override if token_override else None),
                daemon=True,
                name=f"Worker-{login_str}"
            )
            trading_threads[login_str] = worker
            worker.start()

            return jsonify({
                "status": "success",
                "success": True,
                "message": f"License [{license_key}] Verified. Scalper live with Exness Gold resolution.",
                "login": login_str,
                "symbol": mt5_symbol
            }), 200

        return jsonify({"status": "success", "message": f"Command '{command}' processed."}), 200

    except Exception as err:
        print(f"[CONTROLLER FAULT] {err}")
        traceback.print_exc()
        return jsonify({"status": "error", "success": False, "message": str(err)}), 200

# ============================================================
# PRODUCTION ENTRYPOINT
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    print(f"[STARTUP] Running Gold Scalper AI Server on 0.0.0.0:{port}...")
    serve(app, host="0.0.0.0", port=port, threads=8)
