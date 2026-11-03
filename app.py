import os
import sys
import json
import sqlite3
import asyncio
import threading
import datetime
import traceback
from collections import deque
from flask import Flask, request, jsonify
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
# GLOBAL EXCEPTION HANDLER (PURE JSON RESPONSES ONLY)
# ============================================================
@app.errorhandler(Exception)
def handle_exception(e):
    """
    Forces Flask to always reply with valid JSON whenever an error or a 404/500 occurs,
    preventing HTML response mismatches on Bolt and mobile web interfaces.
    """
    if isinstance(e, HTTPException):
        return jsonify({
            "status": "error",
            "success": False,
            "message": e.description,
            "code": e.code
        }), e.code

    # Log full traceback for debugging on Render / Cloud logs
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
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.db")

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

                # Update live telemetry for GET /api/status queries
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
def health_root():
    return jsonify({
        "status": "online",
        "service": "Gold Scalper AI Engine",
        "compatible_frontend": "https://gold-mobile-ea-web-a-5m0x.bolt.host"
    }), 200

# Metadata retrieval for auto-populating fields on Bolt UI
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

# Live telemetry endpoint
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

# ============================================================
# PRODUCTION ENTRYPOINT
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    print(f"[STARTUP] Running Gold Scalper AI Server on 0.0.0.0:{port}...")
    serve(app, host="0.0.0.0", port=port, threads=8)
