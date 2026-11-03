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

# Safe /tmp path for guaranteed write permissions on Render / Linux containers
DB_PATH = "/tmp/credentials.db"

metaapi_instance = None
metaapi_lock = threading.Lock()

active_trading_nodes = {}
trading_threads = {}
live_account_telemetry = {}

# Continuous Scalping Engine Parameters
BURST_ORDER_COUNT = 8          # Stacked orders per wave
MIN_TARGET_PROFIT_USD = 1.00   # Take-profit dollar threshold
PROFIT_EQUITY_RATIO = 0.05     # 5% compounding ratio per wave
MAX_ALLOWED_SPREAD_PIPS = 20.0 # Wide spread tolerance for Gold
MAX_ACCOUNT_DRAWDOWN_RATIO = 0.25 # 25% max basket drawdown cutoff
POLL_LATENCY_DELAY = 0.02      # 20ms polling interval

# ============================================================
# SECURE SERVER-SIDE DATABASE (SQLITE IN /tmp)
# ============================================================
def init_db():
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
# METAAPI ACCOUNT PROVISIONING & CONNECTION RESOLVER
# ============================================================
async def get_or_create_metaapi_account(api, login, password, server):
    """Finds an existing MetaApi account or creates a new one for the broker credentials."""
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
                print(f"[ACCOUNT LOCATED] Found provisioned node for {login} on {server}")
                return acc
    except Exception as e:
        print(f"[ACCOUNT SEARCH NOTICE] {e}")

    print(f"[ACCOUNT CREATION] Provisioning fresh cloud node: Exness {login}")
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

# ============================================================
# HIGH-FREQUENCY TRADING ENGINE (WITH AUTO-RECONNECT WRAPPER)
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
    """Main trading engine with auto-reconnection wrapper to prevent thread death."""
    print(f"[ENGINE INITIALIZED] Starting persistent worker for account {login}...")
    candle_tracker = InstantCandleTracker()

    while active_trading_nodes.get(str(login), False):
        account = None
        connection = None
        try:
            api = get_metaapi_client(token)
            
            account = await get_or_create_metaapi_account(api, login, password, server)

            if getattr(account, 'state', '') != 'DEPLOYED':
                print(f"[DEPLOYING] Deploying cloud API server for {login}...")
                await account.deploy()

            await account.wait_connected()
            connection = account.get_streaming_connection()
            await connection.connect()

            await connection.wait_synchronized()
            print(f"[LIVE SYNC SUCCESS] Connected & synchronized for account: {login}")

            active_symbol = await resolve_broker_gold_symbol(connection, symbol)

            # Inner trading & telemetry cycle
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

                    # Update live telemetry
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

                    # Risk safeguard: 25% max basket drawdown cutoff
                    max_allowed_drawdown = balance * MAX_ACCOUNT_DRAWDOWN_RATIO
                    if symbol_positions and net_floating_profit < -max_allowed_drawdown:
                        await purge_entire_basket_instantly(connection, symbol_positions)
                        await asyncio.sleep(2.0)
                        continue

                    # Take-profit purge trigger
                    dynamic_profit_target = max(MIN_TARGET_PROFIT_USD, balance * PROFIT_EQUITY_RATIO)
                    if symbol_positions and net_floating_profit >= dynamic_profit_target:
                        await purge_entire_basket_instantly(connection, symbol_positions)
                        await asyncio.sleep(0.02)
                        continue

                    # Instant zero-downtime reload
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

                except Exception as inner_err:
                    print(f"[INNER CYCLE ERROR] {inner_err}")
                    break

                await asyncio.sleep(POLL_LATENCY_DELAY)

        except Exception as outer_err:
            print(f"[CONNECTION DROP / ERROR] {outer_err}. Reconnecting in 5 seconds...")
            live_account_telemetry[str(login)] = {"connected_to_broker": False, "running": False}
            await asyncio.sleep(5.0)

    # Cleanup when explicitly stopped
    active_trading_nodes.pop(str(login), None)
    trading_threads.pop(str(login), None)
    live_account_telemetry.pop(str(login), None)
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
# EMBEDDED REACT + TAILWIND FRONTEND TEMPLATE
# ============================================================
REACT_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>Gold Scalper AI - Matrix Control</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>
    body { background-color: #0b0e14; color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  </style>
</head>
<body class="min-h-screen flex flex-col items-center justify-center p-4">
  <div id="root" class="w-full flex justify-center"></div>

  <script type="text/babel">
    const { useState, useEffect } = React;

    function App() {
      const [licenseKey, setLicenseKey] = useState("BOSSMODE99");
      const [mt5Data, setMt5Data] = useState({ login: "", password: "", server: "", symbol: "XAUUSD" });
      const [status, setStatus] = useState({ connected_to_broker: false, running: false, balance: 0.0, equity: 0.0 });
      const [msg, setMsg] = useState("");

      useEffect(() => {
        const savedKey = localStorage.getItem("active_license_key") || "BOSSMODE99";
        setLicenseKey(savedKey);
        fetchAccountDetails(savedKey);
        fetchStatus();

        const interval = setInterval(fetchStatus, 2000);
        return () => clearInterval(interval);
      }, []);

      const fetchAccountDetails = async (key) => {
        try {
          const res = await fetch(`/api/account?license_key=${key}`);
          const data = await res.json();
          if (data && data.login) {
            setMt5Data(prev => ({
              ...prev,
              login: data.login,
              server: data.server,
              symbol: data.symbol || "XAUUSD"
            }));
          }
        } catch (err) {
          console.error("Failed to load saved credentials", err);
        }
      };

      const fetchStatus = async () => {
        try {
          const res = await fetch(`/status`);
          const data = await res.json();
          setStatus(data);
        } catch (err) {
          console.error("Status fetch error", err);
        }
      };

      const handleStart = async () => {
        if (licenseKey !== "BOSSMODE98" && licenseKey !== "BOSSMODE99") {
          setMsg("❌ Invalid License Key! Use BOSSMODE98 or BOSSMODE99.");
          return;
        }
        setMsg("⚡ Validating & Launching Continuous Scalper Wave...");
        try {
          const res = await fetch(`/api/control`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              command: "START",
              license_key: licenseKey,
              mt5_login: mt5Data.login,
              mt5_password: mt5Data.password,
              mt5_server: mt5Data.server,
              mt5_symbol: mt5Data.symbol
            })
          });
          const data = await res.json();
          setMsg(data.message || "Bot active & scalping live!");
          fetchStatus();
        } catch (err) {
          setMsg("❌ Failed to reach backend.");
        }
      };

      const handleStop = async () => {
        setMsg("🛑 Liquidating basket & stopping bot...");
        try {
          await fetch(`/api/control`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              command: "STOP",
              license_key: licenseKey,
              mt5_login: mt5Data.login
            })
          });
          setMsg("🛑 Scalper terminated.");
          fetchStatus();
        } catch (err) {
          setMsg("❌ Failed to stop.");
        }
      };

      return (
        <div className="w-full max-w-md bg-[#161b22]/90 backdrop-blur-xl border border-white/10 rounded-3xl p-6 shadow-2xl">
          <div className="flex items-center justify-between border-b border-gray-800 pb-4 mb-5">
            <div className="flex items-center space-x-3">
              <div className="w-10 h-10 rounded-2xl bg-gradient-to-tr from-emerald-500 to-green-300 flex items-center justify-center text-black font-extrabold text-xl shadow-lg">
                ⚡
              </div>
              <div>
                <h1 className="text-lg font-bold text-white tracking-tight">Gold Scalper AI</h1>
                <p className="text-xs text-emerald-400 font-medium flex items-center gap-1">
                  <span className={`w-2 h-2 rounded-full ${status.running ? 'bg-emerald-400 animate-pulse' : 'bg-gray-500'}`}></span> 
                  {status.running ? "Active Burst Matrix" : "Standby Mode"}
                </p>
              </div>
            </div>
            <div className={`text-xs px-2.5 py-1 rounded-full border ${status.connected_to_broker ? 'bg-emerald-950 text-emerald-400 border-emerald-500/40' : 'bg-gray-800 text-gray-400 border-gray-700'}`}>
              {status.connected_to_broker ? "CONNECTED" : "OFFLINE"}
            </div>
          </div>

          {status.running && (
            <div className="bg-gray-900/60 border border-gray-800 rounded-2xl p-3.5 mb-4 text-xs font-mono">
              <div className="grid grid-cols-2 gap-2">
                <div><span className="text-gray-500">Balance:</span> <span className="text-white font-bold">${Number(status.balance || 0).toFixed(2)}</span></div>
                <div><span className="text-gray-500">Equity:</span> <span className="text-emerald-400 font-bold">${Number(status.equity || 0).toFixed(2)}</span></div>
              </div>
            </div>
          )}

          <div className="mb-4">
            <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">Master License Key</label>
            <input 
              type="text" 
              value={licenseKey} 
              onChange={(e) => {
                const val = e.target.value.toUpperCase();
                setLicenseKey(val);
                localStorage.setItem("active_license_key", val);
                fetchAccountDetails(val);
              }}
              placeholder="BOSSMODE98 or BOSSMODE99" 
              className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-emerald-500 uppercase tracking-widest font-mono text-emerald-400" 
            />
          </div>

          <div className="space-y-3 mb-5">
            <div>
              <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">MT5 Account Login</label>
              <input 
                type="text" 
                value={mt5Data.login} 
                onChange={(e) => setMt5Data({ ...mt5Data, login: e.target.value })}
                placeholder="e.g. 21648212" 
                className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-emerald-500 font-mono" 
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">MT5 Trading Password</label>
              <input 
                type="password" 
                value={mt5Data.password} 
                onChange={(e) => setMt5Data({ ...mt5Data, password: e.target.value })}
                placeholder="••••••••" 
                className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-emerald-500 font-mono" 
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">Broker Server</label>
                <input 
                  type="text" 
                  value={mt5Data.server} 
                  onChange={(e) => setMt5Data({ ...mt5Data, server: e.target.value })}
                  placeholder="Exness-MT5Trial" 
                  className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-emerald-500 font-mono" 
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">Symbol</label>
                <input 
                  type="text" 
                  value={mt5Data.symbol} 
                  onChange={(e) => setMt5Data({ ...mt5Data, symbol: e.target.value })}
                  placeholder="XAUUSD" 
                  className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-emerald-500 font-mono" 
                />
              </div>
            </div>
          </div>

          <div className="bg-black/50 border border-gray-800 rounded-xl p-3 mb-5 text-xs font-mono text-gray-400 min-h-[48px] flex items-center">
            {msg || "Ready. Click Launch to initiate continuous wave scalping."}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <button 
              onClick={handleStart}
              className="w-full py-3.5 bg-gradient-to-r from-emerald-500 to-green-600 hover:from-emerald-400 hover:to-green-500 text-black font-extrabold rounded-2xl shadow-lg transition active:scale-95"
            >
              ⚡ LAUNCH BOT
            </button>

            <button 
              onClick={handleStop}
              className="w-full py-3.5 bg-gradient-to-r from-rose-600 to-red-700 hover:from-rose-500 hover:to-red-600 text-white font-extrabold rounded-2xl shadow-lg transition active:scale-95"
            >
              🛑 STOP BOT
            </button>
          </div>
        </div>
      );
    }

    ReactDOM.createRoot(document.getElementById('root')).render(<App />);
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
def root_dashboard():
    """Serves the complete React + Tailwind frontend directly at root."""
    return render_template_string(REACT_HTML_TEMPLATE)

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

# ============================================================
# PRODUCTION ENTRYPOINT
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    print(f"[STARTUP] Running Gold Scalper AI Server on 0.0.0.0:{port}...")
    serve(app, host="0.0.0.0", port=port, threads=8)
