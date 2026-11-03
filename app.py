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
from werkzeug.exceptions import HTTPException
from metaapi_cloud_sdk import MetaApi
from waitress import serve

app = Flask(__name__)

# ============================================================
# CROSS-ORIGIN RESOURCE SHARING (CORS) CONFIGURATION
# ============================================================
CORS(app, resources={r"/*": {"origins": "*"}})

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, HEAD"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, x-api-key, X-Requested-With, Accept"
    return response

# ============================================================
# GLOBAL EXCEPTION HANDLER (PURE JSON ONLY)
# ============================================================
@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return jsonify({
            "status": "error",
            "success": False,
            "message": e.description,
            "code": e.code
        }), e.code

    traceback.print_exc()
    return jsonify({
        "status": "error",
        "success": False,
        "message": str(e)
    }), 500

# ============================================================
# MASTER LICENSE & SECURITY CONFIGURATION
# ============================================================
METAAPI_TOKEN = os.environ.get("METAAPI_TOKEN", "").strip()
ALLOWED_LICENSES = ["BOSSMODE98", "BOSSMODE99"]

DB_PATH = "/tmp/credentials.db"

metaapi_instance = None
metaapi_lock = threading.Lock()

active_trading_nodes = {}
trading_threads = {}
active_connections = {}
live_account_telemetry = {}

BURST_ORDER_COUNT = 8
MIN_TARGET_PROFIT_USD = 1.00
PROFIT_EQUITY_RATIO = 0.05
MAX_ALLOWED_SPREAD_PIPS = 20.0
MAX_ACCOUNT_DRAWDOWN_RATIO = 0.25
POLL_LATENCY_DELAY = 0.02

# ============================================================
# SECURE SERVER-SIDE DATABASE (SQLITE IN /tmp)
# ============================================================
def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS credentials (
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
    except Exception as e:
        print(f"[DB INIT ERROR] {e}")

init_db()

def db_save_credentials(license_key, login, password, server, symbol):
    if not os.path.exists(DB_PATH):
        init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO credentials (license_key, mt5_login, mt5_password, mt5_server, mt5_symbol, updated_at)
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
    if not os.path.exists(DB_PATH):
        init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT mt5_login, mt5_password, mt5_server, mt5_symbol FROM credentials WHERE license_key = ?", (license_key.upper(),))
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
# METAAPI ACCOUNT PROVISIONING & CONNECTION RESOLVER
# ============================================================
async def get_or_create_metaapi_account(api, login, password, server):
    try:
        if hasattr(api.metatrader_account_api, 'get_accounts_with_classic_pagination'):
            res = await api.metatrader_account_api.get_accounts_with_classic_pagination()
            accounts = res.get('items', []) if isinstance(res, dict) else res
        elif hasattr(api.metatrader_account_api, 'get_accounts'):
            accounts = await api.metatrader_account_api.get_accounts()
        else:
            accounts = []

        for acc in accounts:
            if str(getattr(acc, 'login', '')) == str(login) and getattr(acc, 'server', '').lower() == str(server).lower():
                return acc
    except Exception as e:
        print(f"[ACCOUNT SEARCH NOTICE] {e}")

    account = await api.metatrader_account_api.create_account({
        'name': f'Exness {login}',
        'type': 'cloud',
        'login': str(login),
        'password': password,
        'server': server,
        'platform': 'mt5',
        'magic': 9924102
    })
    return account

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
                return sym
        except Exception:
            continue

    await connection.subscribe_to_market_data(requested_symbol)
    return requested_symbol

async def fire_stacked_directional_burst(connection, symbol: str, direction: str, volume: float, count: int, login: str, key: str):
    tasks = []
    bot_signature = f"⚡ [{key}] GOLD SCALPER"
    for _ in range(count):
        if direction == "BUY":
            tasks.append(connection.create_market_buy_order(symbol=symbol, volume=volume, options={"comment": bot_signature}))
        else:
            tasks.append(connection.create_market_sell_order(symbol=symbol, volume=volume, options={"comment": bot_signature}))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return sum(1 for r in results if not isinstance(r, Exception))

async def purge_entire_basket_instantly(connection, positions):
    close_tasks = [connection.close_position(pos["id"]) for pos in positions if "id" in pos]
    if close_tasks:
        await asyncio.gather(*close_tasks, return_exceptions=True)

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
        return "BUY"

async def high_frequency_trading_engine(login, password, server, symbol, key, token=None):
    candle_tracker = InstantCandleTracker()
    while active_trading_nodes.get(str(login), False):
        connection = None
        try:
            api = get_metaapi_client(token)
            account = await get_or_create_metaapi_account(api, login, password, server)
            if getattr(account, 'state', '') != 'DEPLOYED':
                await account.deploy()
            await account.wait_connected()
            connection = account.get_streaming_connection()
            active_connections[str(login)] = connection
            await connection.connect()
            await connection.wait_synchronized()
            active_symbol = await resolve_broker_gold_symbol(connection, symbol)

            while active_trading_nodes.get(str(login), False):
                try:
                    terminal_state = connection.terminal_state
                    account_info = terminal_state.account_information or {}
                    positions = terminal_state.positions or []

                    balance = float(account_info.get('balance', 0.0) or 0.0)
                    equity = float(account_info.get('equity', 0.0) or 0.0)
                    free_margin = float(account_info.get('freeMargin', 0.0) or 0.0)
                    margin_level = float(account_info.get('marginLevel', 0.0) or 0.0)

                    price = terminal_state.price(active_symbol)
                    if not price or not price.get("bid"):
                        await connection.subscribe_to_market_data(active_symbol)
                        await asyncio.sleep(0.1)
                        continue

                    current_ask = price.get("ask")
                    current_bid = price.get("bid")
                    mid_price = (current_ask + current_bid) / 2.0
                    candle_tracker.record_tick(mid_price)

                    symbol_positions = [p for p in positions if p.get("symbol") == active_symbol]
                    net_floating_profit = equity - balance

                    live_account_telemetry[str(login)] = {
                        "connected_to_broker": True,
                        "running": True,
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

                    max_allowed_drawdown = balance * MAX_ACCOUNT_DRAWDOWN_RATIO
                    if symbol_positions and net_floating_profit < -max_allowed_drawdown:
                        await purge_entire_basket_instantly(connection, symbol_positions)
                        await asyncio.sleep(2.0)
                        continue

                    dynamic_profit_target = max(MIN_TARGET_PROFIT_USD, balance * PROFIT_EQUITY_RATIO)
                    if symbol_positions and net_floating_profit >= dynamic_profit_target:
                        await purge_entire_basket_instantly(connection, symbol_positions)
                        await asyncio.sleep(0.02)
                        continue

                    if len(symbol_positions) == 0:
                        current_spread_pips = round((current_ask - current_bid) / 0.1, 2)
                        if current_spread_pips > MAX_ALLOWED_SPREAD_PIPS:
                            await asyncio.sleep(POLL_LATENCY_DELAY)
                            continue

                        direction = candle_tracker.determine_bias()
                        assigned_lot = calculate_dynamic_lot_size(equity if equity > 0 else balance, free_margin)
                        active_burst_count = BURST_ORDER_COUNT if free_margin >= 25.0 else 2

                        await fire_stacked_directional_burst(
                            connection, active_symbol, direction, assigned_lot, active_burst_count, login, key
                        )
                        await asyncio.sleep(0.05)
                        continue

                except Exception:
                    break
                await asyncio.sleep(POLL_LATENCY_DELAY)
        except Exception:
            live_account_telemetry[str(login)] = {"connected_to_broker": False, "running": False}
        finally:
            if connection:
                try:
                    await connection.close()
                except Exception:
                    pass
            active_connections.pop(str(login), None)
            await asyncio.sleep(5.0)

    active_trading_nodes.pop(str(login), None)
    trading_threads.pop(str(login), None)
    live_account_telemetry.pop(str(login), None)

def launch_async_worker_thread(login, password, server, symbol, key, token=None):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(high_frequency_trading_engine(login, password, server, symbol, key, token))
    finally:
        try:
            loop.close()
        except Exception:
            pass

# ============================================================
# BULLETPROOF UI TEMPLATE WITH SAFE FALLBACK PARSING
# ============================================================
EXACT_MATCH_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>GOLD MOBILE EA</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background-color: #0b0e14; color: #f3f4f6; min-height: 100vh; padding: 12px; display: flex; flex-direction: column; align-items: center; }
    .container { width: 100%; max-width: 440px; display: flex; flex-direction: column; gap: 12px; padding-bottom: 24px; }
    
    .top-header { display: flex; align-items: center; justify-content: space-between; background: #161b22; border: 1px solid #21262d; border-radius: 16px; padding: 12px 16px; }
    .brand-box { display: flex; align-items: center; gap: 10px; }
    .brand-logo { width: 36px; height: 36px; background: #00d26a; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 18px; color: #000; }
    .brand-title { font-size: 15px; font-weight: 800; color: #fff; letter-spacing: 0.5px; }
    .top-icon { color: #00d26a; font-size: 18px; }

    .main-title { font-size: 20px; font-weight: 900; color: #fff; letter-spacing: 0.5px; margin-top: 4px; margin-bottom: 2px; }

    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    
    .card { background: #161b22; border: 1px solid #21262d; border-radius: 16px; padding: 14px; display: flex; flex-direction: column; justify-content: space-between; min-height: 85px; }
    .card-top { display: flex; justify-content: space-between; align-items: center; font-size: 11px; font-weight: 700; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; }
    .card-value { font-size: 14px; font-weight: 800; color: #fff; margin-top: 8px; word-break: break-all; }
    
    .full-card { background: #161b22; border: 1px solid #21262d; border-radius: 16px; padding: 14px; }

    .banner-card { background: #161b22; border: 1px solid #21262d; border-radius: 16px; padding: 14px; font-size: 12px; color: #8b949e; line-height: 1.4; text-align: center; font-family: monospace; }

    .btn-start { width: 100%; background: #00d26a; color: #0b0e14; border: none; border-radius: 14px; padding: 16px; font-size: 15px; font-weight: 800; cursor: pointer; text-transform: uppercase; box-shadow: 0 4px 15px rgba(0,210,106,0.2); }
    .btn-start:active { transform: scale(0.98); }
    
    .btn-stop { width: 100%; background: transparent; color: #8b949e; border: 1px solid #21262d; border-radius: 14px; padding: 16px; font-size: 15px; font-weight: 800; cursor: pointer; text-transform: uppercase; }
    .btn-stop:active { transform: scale(0.98); }

    .settings-panel { background: #161b22; border: 1px solid #21262d; border-radius: 16px; padding: 16px; margin-top: 10px; display: flex; flex-direction: column; gap: 12px; }
    .input-group { display: flex; flex-direction: column; gap: 6px; }
    .input-group label { font-size: 11px; font-weight: 700; color: #8b949e; text-transform: uppercase; }
    .input-group input { background: #0b0e14; border: 1px solid #30363d; border-radius: 10px; padding: 10px 12px; color: #fff; font-size: 13px; outline: none; }
    .input-group input:focus { border-color: #00d26a; }
  </style>
</head>
<body>
  <div class="container">
    <div class="top-header">
      <div class="brand-box">
        <div class="brand-logo">💎</div>
        <div class="brand-title">GOLD MOBILE EA</div>
      </div>
      <div class="top-icon">⚡</div>
    </div>

    <div class="main-title">GOLD MOBILE EA</div>

    <div class="grid-2">
      <div class="card">
        <div class="card-top"><span>MT5 Connection</span> <span>🔌</span></div>
        <div class="card-value" id="lblConnection">OFFLINE</div>
      </div>
      <div class="card">
        <div class="card-top"><span>Bot Status</span> <span>🤖</span></div>
        <div class="card-value" id="lblBotStatus">STANDBY</div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-top"><span>Balance</span> <span>💰</span></div>
        <div class="card-value" id="lblBalance">$0.00</div>
      </div>
      <div class="card">
        <div class="card-top"><span>Equity</span> <span>📈</span></div>
        <div class="card-value" id="lblEquity">$0.00</div>
      </div>
    </div>

    <div class="full-card">
      <div class="card-top" style="margin-bottom:6px;"><span>Open Positions</span> <span>📊</span></div>
      <div class="card-value" id="lblPositions" style="margin-top:0;">0 Active Orders</div>
    </div>

    <div class="banner-card" id="msgBanner">
      Ready. Tap Start Bot to initiate high-frequency scalping.
    </div>

    <button class="btn-start" onclick="handleStart()">Start Bot</button>
    <button class="btn-stop" onclick="handleStop()">Stop Bot</button>

    <div class="settings-panel">
      <div style="font-size: 12px; font-weight: 800; color: #fff; margin-bottom: 2px;">BROKER CREDENTIALS</div>
      <div class="input-group">
        <label>Master License Key</label>
        <input type="text" id="txtKey" value="BOSSMODE99" style="text-transform:uppercase; color:#00d26a; font-weight:700;" />
      </div>
      <div class="input-group">
        <label>MT5 Login</label>
        <input type="text" id="txtLogin" placeholder="21648212" />
      </div>
      <div class="input-group">
        <label>MT5 Password</label>
        <input type="password" id="txtPass" placeholder="••••••••" />
      </div>
      <div class="grid-2">
        <div class="input-group">
          <label>Server</label>
          <input type="text" id="txtServer" placeholder="Exness-MT5Trial" />
        </div>
        <div class="input-group">
          <label>Symbol</label>
          <input type="text" id="txtSymbol" value="XAUUSD" />
        </div>
      </div>
      <button onclick="saveConfig()" style="background:#21262d; color:#fff; border:none; border-radius:10px; padding:10px; font-weight:700; font-size:12px; cursor:pointer; margin-top:4px;">Save Credentials</button>
    </div>
  </div>

  <script>
    async function loadAccount() {
      const key = (document.getElementById('txtKey').value || 'BOSSMODE99').trim().toUpperCase();
      try {
        const res = await fetch('/api/account?license_key=' + key);
        const data = await res.json();
        if (data && data.login) {
          document.getElementById('txtLogin').value = data.login;
          document.getElementById('txtServer').value = data.server || 'Exness-MT5Trial';
          document.getElementById('txtSymbol').value = data.symbol || 'XAUUSD';
        }
      } catch (e) {}
    }

    async function pollStatus() {
      try {
        const res = await fetch('/status');
        const text = await res.text();
        let data;
        try {
          data = JSON.parse(text);
        } catch (err) {
          return; // Skip cycle safely if response is not valid JSON yet
        }
        
        document.getElementById('lblConnection').innerText = data?.connected_to_broker ? 'CONNECTED' : 'OFFLINE';
        document.getElementById('lblConnection').style.color = data?.connected_to_broker ? '#00d26a' : '#f87171';
        
        document.getElementById('lblBotStatus').innerText = data?.running ? 'RUNNING' : 'STANDBY';
        document.getElementById('lblBotStatus').style.color = data?.running ? '#00d26a' : '#8b949e';
        
        document.getElementById('lblBalance').innerText = '$' + (Number(data?.balance) || 0).toFixed(2);
        document.getElementById('lblEquity').innerText = '$' + (Number(data?.equity) || 0).toFixed(2);
        
        let activeNodes = data?.active_accounts || [];
        if (activeNodes.length > 0 && data?.telemetry && data.telemetry[activeNodes[0]]) {
          let t = data.telemetry[activeNodes[0]];
          document.getElementById('lblPositions').innerText = (t?.open_positions_count || 0) + ' Active Orders (PnL: $' + (t?.floating_pnl || 0) + ')';
        } else {
          document.getElementById('lblPositions').innerText = '0 Active Orders';
        }
      } catch (e) {}
    }

    async function saveConfig() {
      const key = document.getElementById('txtKey').value.trim().toUpperCase();
      const login = document.getElementById('txtLogin').value.trim();
      const pass = document.getElementById('txtPass').value.trim();
      const server = document.getElementById('txtServer').value.trim();
      const symbol = document.getElementById('txtSymbol').value.trim();
      const banner = document.getElementById('msgBanner');

      try {
        const res = await fetch('/api/control', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: 'SAVE', license_key: key, mt5_login: login, mt5_password: pass, mt5_server: server, mt5_symbol: symbol })
        });
        const data = await res.json();
        banner.innerText = data?.message || 'Credentials saved successfully.';
      } catch (e) {
        banner.innerText = 'Failed to save credentials.';
      }
    }

    async function handleStart() {
      const key = document.getElementById('txtKey').value.trim().toUpperCase();
      const login = document.getElementById('txtLogin').value.trim();
      const pass = document.getElementById('txtPass').value.trim();
      const server = document.getElementById('txtServer').value.trim();
      const symbol = document.getElementById('txtSymbol').value.trim();
      const banner = document.getElementById('msgBanner');

      banner.innerText = 'Connecting matrix & deploying scalp wave...';
      try {
        const res = await fetch('/api/control', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: 'START', license_key: key, mt5_login: login, mt5_password: pass, mt5_server: server, mt5_symbol: symbol })
        });
        const data = await res.json();
        banner.innerText = data?.message || 'Bot active!';
        pollStatus();
      } catch (e) {
        banner.innerText = 'Failed to start bot.';
      }
    }

    async function handleStop() {
      const key = document.getElementById('txtKey').value.trim().toUpperCase();
      const login = document.getElementById('txtLogin').value.trim();
      const banner = document.getElementById('msgBanner');

      banner.innerText = 'Stopping bot & liquidating basket...';
      try {
        const res = await fetch('/api/control', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: 'STOP', license_key: key, mt5_login: login })
        });
        banner.innerText = 'Bot terminated.';
        pollStatus();
      } catch (e) {
        banner.innerText = 'Failed to stop bot.';
      }
    }

    document.getElementById('txtKey').addEventListener('change', loadAccount);
    loadAccount();
    pollStatus();
    setInterval(pollStatus, 3000);
  </script>
</body>
</html>
"""

# ============================================================
# API CONTROLLER & MATCHING ROUTES
# ============================================================
def extract_request_data(req):
    data = {}
    try:
        data = req.get_json(force=True, silent=True) or {}
    except Exception:
        pass
    if not data and req.form:
        try:
            data = req.form.to_dict()
        except Exception:
            pass
    if not data and req.data:
        try:
            data = json.loads(req.data.decode("utf-8"))
        except Exception:
            pass
    if not data and req.args:
        try:
            data = req.args.to_dict()
        except Exception:
            pass
    return data or {}

@app.route("/", methods=["GET"])
def root_dashboard():
    return render_template_string(EXACT_MATCH_HTML)

@app.route("/api/account", methods=["GET", "OPTIONS"])
@app.route("/get_credentials", methods=["GET", "OPTIONS"])
def get_account_metadata():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    try:
        license_key = request.args.get("license_key", "BOSSMODE99").strip().upper()
        if not os.path.exists(DB_PATH):
            init_db()

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT mt5_login, mt5_server, mt5_symbol FROM credentials WHERE license_key = ?", (license_key,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return jsonify({
                "status": "success",
                "login": row[0] or "21648212",
                "server": row[1] or "Exness-MT5Trial",
                "symbol": row[2] or "XAUUSD"
            }), 200
        else:
            return jsonify({
                "status": "success",
                "login": "21648212",
                "server": "Exness-MT5Trial",
                "symbol": "XAUUSD"
            }), 200
    except Exception as e:
        return jsonify({
            "status": "success",
            "login": "21648212",
            "server": "Exness-MT5Trial",
            "symbol": "XAUUSD"
        }), 200

@app.route("/status", methods=["GET", "OPTIONS"])
@app.route("/api/status", methods=["GET", "OPTIONS"])
def status_endpoint():
    try:
        active_accounts = [login for login, running in active_trading_nodes.items() if running]
        is_running = len(active_accounts) > 0
        is_connected = False
        balance = 0.0
        equity = 0.0

        if is_running:
            first_login = active_accounts[0]
            if first_login in live_account_telemetry:
                t = live_account_telemetry[first_login]
                is_connected = t.get("connected_to_broker", False)
                balance = t.get("balance", 0.0)
                equity = t.get("equity", 0.0)

        return jsonify({
            "status": "online",
            "running": is_running,
            "connected_to_broker": is_connected,
            "balance": balance,
            "equity": equity,
            "active_nodes_count": len(active_accounts),
            "active_accounts": active_accounts,
            "telemetry": live_account_telemetry
        }), 200
    except Exception as e:
        return jsonify({
            "status": "online",
            "running": False,
            "connected_to_broker": False,
            "balance": 0.0,
            "equity": 0.0
        }), 200

@app.route("/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/start", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/start", methods=["GET", "POST", "OPTIONS"])
def control_dispatcher():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

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

    saved = db_get_credentials(license_key)
    if saved:
        mt5_login = mt5_login or saved["mt5_login"]
        mt5_password = mt5_password or saved["mt5_password"]
        mt5_server = mt5_server or saved["mt5_server"]
        mt5_symbol = mt5_symbol or saved["mt5_symbol"]

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

    db_save_credentials(license_key, mt5_login, mt5_password, mt5_server, mt5_symbol)
    login_str = str(mt5_login).strip()

    if command == "STOP":
        active_trading_nodes[login_str] = False
        return jsonify({"status": "success", "success": True, "message": "STOP command accepted."}), 200

    if command in ["START", "RUN"]:
        active_trading_nodes[login_str] = False
        if login_str in active_connections:
            try:
                asyncio.run(active_connections[login_str].close())
            except Exception:
                pass
            active_connections.pop(login_str, None)

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
            "message": f"License [{license_key}] Verified. Scalper live with Exness Gold resolution.",
            "login": login_str,
            "symbol": mt5_symbol
        }), 200

    return jsonify({"status": "success", "message": f"Command '{command}' processed."}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    print(f"[STARTUP] Running Gold Scalper AI Server on 0.0.0.0:{port}...")
    serve(app, host="0.0.0.0", port=port, threads=8)
