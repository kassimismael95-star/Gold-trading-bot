import os
import sys
import json
import asyncio
import threading
import datetime
import traceback
from collections import deque
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from metaapi_cloud_sdk import MetaApi
from waitress import serve

app = Flask(__name__)
# Enable full CORS across all origins
CORS(app, resources={r"/*": {"origins": "*"}})

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, HEAD"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

# ============================================================
# MASTER LICENSE & SECURITY INTEGRITY
# ============================================================
METAAPI_TOKEN = os.environ.get("METAAPI_TOKEN", "").strip()

# ============================================================
# SYSTEM STATE STORAGE PIPELINES
# ============================================================
metaapi_instance = None
metaapi_lock = threading.Lock()
active_trading_nodes = {}
trading_threads = {}

# ============================================================
# NON-STOP SCALPING PARAMETERS
# ============================================================
BURST_ORDER_COUNT = 8          # Clustered order waves (6-10 positions)
MIN_TARGET_PROFIT_USD = 1.00   # Fast micro-scalp purge trigger
PROFIT_EQUITY_RATIO = 0.05     # Compounding profit ratio (~5% per wave)
MAX_ALLOWED_SPREAD_PIPS = 9.0  # Gold spread threshold (0.90 USD on Gold)
POLL_LATENCY_DELAY = 0.01      # Continuous 10ms execution loop

def get_metaapi_client(override_token: str = None):
    """Provides thread-safe initialization of the MetaApi controller."""
    global metaapi_instance
    token = (override_token or os.environ.get("METAAPI_TOKEN", "")).strip()
    if not token:
        print("[WARNING] METAAPI_TOKEN is not set in environment.")
    with metaapi_lock:
        if metaapi_instance is None or override_token:
            metaapi_instance = MetaApi(token)
    return metaapi_instance

def calculate_video_lot_size(equity: float) -> float:
    """
    Tiered lot escalation for continuous aggressive compounding:
    - Equity < $50: 0.05
    - Equity $50 - $1,000: 0.10
    - Equity $1,000 - $3,500: 0.50
    - Equity $3,500 - $15,000: 1.00
    - Equity $15,000 - $35,000: 1.50
    - Equity $35,000 - $60,000: 2.00
    - Equity $60,000+: 3.00
    """
    if equity < 50.0:
        return 0.05
    elif equity < 1000.0:
        return 0.10
    elif equity < 3500.0:
        return 0.50
    elif equity < 15000.0:
        return 1.00
    elif equity < 35000.0:
        return 1.50
    elif equity < 60000.0:
        return 2.00
    else:
        return 3.00

# ============================================================
# CANDLE & TICK VELOCITY MOMENTUM ENGINE
# ============================================================
class InstantCandleTracker:
    """Tracks sub-second and 1-minute candle momentum on every tick."""
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
        
        # 1. 1-Minute Candle Directional Bias
        if self.candle_open is not None:
            if current_price > self.candle_open:
                return "BUY"
            elif current_price < self.candle_open:
                return "SELL"
        
        # 2. Tick Velocity Fallback
        if len(self.ticks) >= 3:
            delta = self.ticks[-1] - self.ticks[0]
            return "BUY" if delta >= 0 else "SELL"
            
        return "BUY"

# ============================================================
# PARALLEL EXECUTION & PURGE ENGINES
# ============================================================
async def fire_stacked_directional_burst(connection, symbol: str, direction: str, volume: float, count: int, login: str):
    """Deploys a dense multi-order burst simultaneously in one direction."""
    tasks = []
    for _ in range(count):
        if direction == "BUY":
            tasks.append(connection.create_market_buy_order(symbol, volume, 0, 0))
        else:
            tasks.append(connection.create_market_sell_order(symbol, volume, 0, 0))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    successful = sum(1 for r in results if not isinstance(r, Exception))
    print(f"[BURST DEPLOYED] {login} -> {successful}/{count} {direction} orders executed @ {volume} lots on {symbol}")

async def purge_entire_basket_instantly(connection, positions):
    """Simultaneously liquidates all open positions across the terminal."""
    close_tasks = [
        connection.close_position(pos["id"])
        for pos in positions
        if "id" in pos
    ]
    if close_tasks:
        results = await asyncio.gather(*close_tasks, return_exceptions=True)
        print(f"[LIQUIDATOR] Purged {len(results)} positions in parallel.")

# ============================================================
# BULLETPROOF ACCOUNT PROVISIONING & CONNECTION RESOLVER
# ============================================================
async def get_or_create_metaapi_account(api, login, password, server):
    """Prevents API errors by reusing existing accounts across all SDK versions."""
    login_str = str(login).strip()
    existing_account = None

    try:
        if hasattr(api.metatrader_account_api, 'get_accounts_with_classic_pagination'):
            res = await api.metatrader_account_api.get_accounts_with_classic_pagination()
            accounts = res.get('items', []) if isinstance(res, dict) else res
        elif hasattr(api.metatrader_account_api, 'get_accounts'):
            accounts = await api.metatrader_account_api.get_accounts()
        else:
            accounts = []

        for acc in accounts:
            acc_login = str(getattr(acc, 'login', ''))
            acc_server = str(getattr(acc, 'server', ''))
            if acc_login == login_str and acc_server.lower() == server.lower():
                existing_account = acc
                break
    except Exception as fetch_err:
        print(f"[ACCOUNT SEARCH NOTICE] {fetch_err}, searching direct deployment...")

    if existing_account:
        print(f"[ACCOUNT FOUND] Reusing MetaApi cloud instance for {login_str}")
        if getattr(existing_account, 'state', '') != 'DEPLOYED':
            try:
                await existing_account.deploy()
            except Exception:
                pass
        return existing_account

    print(f"[ACCOUNT CREATION] Initializing new MetaApi cloud instance for {login_str} on {server}")
    new_acc = await api.metatrader_account_api.create_account({
        "name": f"TradingNode_{login_str}",
        "type": "cloud",
        "login": login_str,
        "password": password,
        "server": server,
        "platform": "mt5",
        "magic": 9924102,
    })
    return new_acc

# ============================================================
# NON-STOP HIGH-FREQUENCY EXECUTION CORE
# ============================================================
async def high_frequency_trading_engine(login, password, server, symbol, token=None):
    """Continuous trading engine with instant zero-downtime reloads."""
    print(f"[SYSTEM INITIATED] Connecting active matrix for account {login} on {server} targeting {symbol}")
    account = None
    candle_tracker = InstantCandleTracker()

    try:
        api = get_metaapi_client(token)
        account = await get_or_create_metaapi_account(api, login, password, server)

        print(f"[CONNECTING] Synchronizing real-time terminal stream for: {login}")
        await account.wait_connected()
        connection = account.get_streaming_connection()
        await connection.connect()
        await connection.wait_synchronized()
        print(f"[CORE LIVE] Non-Stop Active Scalper running for: {login}")

        while active_trading_nodes.get(str(login), False):
            account_info = account.account_information or {}
            equity = float(account_info.get("equity", 0) or 0)
            balance = float(account_info.get("balance", 0) or 0)

            terminal_state = connection.terminal_state
            price = terminal_state.price(symbol)
            if not price:
                await asyncio.sleep(POLL_LATENCY_DELAY)
                continue

            current_ask = price.get("ask")
            current_bid = price.get("bid")
            if current_ask is None or current_bid is None:
                await asyncio.sleep(POLL_LATENCY_DELAY)
                continue

            mid_price = (current_ask + current_bid) / 2.0
            candle_tracker.record_tick(mid_price)

            # Spread gatekeeper
            current_spread_pips = round((current_ask - current_bid) / 0.1, 2)
            if current_spread_pips > MAX_ALLOWED_SPREAD_PIPS:
                await asyncio.sleep(POLL_LATENCY_DELAY)
                continue

            positions = terminal_state.positions or []
            symbol_positions = [p for p in positions if p.get("symbol") == symbol]
            net_floating_profit = equity - balance

            dynamic_profit_target = max(MIN_TARGET_PROFIT_USD, balance * PROFIT_EQUITY_RATIO)

            # 1. BASKET TAKE-PROFIT PURGE TRIGGER
            if symbol_positions and net_floating_profit >= dynamic_profit_target:
                print(f"[TARGET HIT] Purging: +${net_floating_profit:.2f} >= Target: ${dynamic_profit_target:.2f}")
                await purge_entire_basket_instantly(connection, symbol_positions)
                await asyncio.sleep(0.01)
                continue

            # 2. ZERO-DOWNTIME INSTANT RELOAD (NEVER RESTS)
            if len(symbol_positions) == 0:
                direction = candle_tracker.determine_bias()
                assigned_lot = calculate_video_lot_size(equity if equity > 0 else balance)
                
                print(f"[NON-STOP RELOAD] Firing {direction} cluster on {symbol} (Balance: ${balance:.2f}, Lots: {assigned_lot})")
                await fire_stacked_directional_burst(
                    connection, symbol, direction, assigned_lot, BURST_ORDER_COUNT, login
                )
                await asyncio.sleep(0.02)
                continue

            await asyncio.sleep(POLL_LATENCY_DELAY)

    except Exception as e:
        print(f"[CRITICAL ENGINE ERROR] Node failure for {login}: {e}")
        traceback.print_exc()
    finally:
        active_trading_nodes.pop(str(login), None)
        trading_threads.pop(str(login), None)
        print(f"[ENGINE STOPPED] Trading node terminated for: {login}")

# ============================================================
# THREAD DISPATCH GATEWAY WRAPPER
# ============================================================
def launch_async_worker_thread(login, password, server, symbol, token=None):
    """Spawns an isolated asyncio loop per MT5 account."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(high_frequency_trading_engine(login, password, server, symbol, token))
    except Exception as thread_err:
        print(f"[THREAD ERROR] Account {login} thread terminated: {thread_err}")
        traceback.print_exc()
    finally:
        try:
            loop.close()
        except Exception:
            pass

# ============================================================
# UNIVERSAL MULTI-FORMAT PAYLOAD EXTRACTION
# ============================================================
def extract_request_data(req):
    """Extracts dictionary payload regardless of Content-Type or method."""
    data = {}
    
    try:
        data = req.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}

    if not data and req.form:
        try:
            data = req.form.to_dict()
        except Exception:
            pass

    if not data and req.data:
        try:
            raw_str = req.data.decode("utf-8")
            data = json.loads(raw_str)
        except Exception:
            pass

    if not data and req.args:
        try:
            data = req.args.to_dict()
        except Exception:
            pass

    return data or {}

# ============================================================
# UNIVERSAL CONTROLLER ROUTE DISPATCHER
# ============================================================
@app.route("/", methods=["GET", "POST", "OPTIONS"])
@app.route("/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/start", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/start", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/trade", methods=["GET", "POST", "OPTIONS"])
def universal_trade_controller():
    """
    Handles all incoming endpoints and returns 200 OK responses.
    """
    if request.method == "OPTIONS":
        return jsonify({"status": "ok", "message": "Preflight accepted"}), 200

    try:
        data = extract_request_data(request)
        print(f"[INCOMING DISPATCH] Endpoint: {request.path} | Method: {request.method} | Data: {data}")

        command = str(data.get("command") or data.get("action") or "START").strip().upper()
        
        token_override = str(
            data.get("metaapi_token") or data.get("token") or request.headers.get("Authorization", "")
        ).replace("Bearer ", "").strip()

        # Multi-alias credential resolution with environment variable fallbacks
        mt5_login = str(
            data.get("mt5_login") or data.get("login") or data.get("account") or data.get("account_id") or data.get("user") or os.environ.get("MT5_LOGIN", "")
        ).strip()

        mt5_password = str(
            data.get("mt5_password") or data.get("password") or data.get("pass") or os.environ.get("MT5_PASSWORD", "")
        ).strip()

        mt5_server = str(
            data.get("mt5_server") or data.get("server") or data.get("broker") or os.environ.get("MT5_SERVER", "")
        ).strip()

        mt5_symbol = str(
            data.get("mt5_symbol") or data.get("symbol") or os.environ.get("MT5_SYMBOL", "XAUUSDm")
        ).strip()

        # Check for missing credentials
        if not mt5_login or not mt5_password or not mt5_server:
            missing_fields = []
            if not mt5_login: missing_fields.append("mt5_login")
            if not mt5_password: missing_fields.append("mt5_password")
            if not mt5_server: missing_fields.append("mt5_server")
            
            print(f"[VALIDATION FAILED] Missing fields: {missing_fields}")
            return jsonify({
                "status": "error",
                "success": False,
                "message": f"Missing credentials: {', '.join(missing_fields)}. Please enter them or configure environment variables."
            }), 200

        login_str = str(mt5_login).strip()

        if command == "STOP":
            active_trading_nodes[login_str] = False
            return jsonify({
                "status": "success",
                "success": True,
                "message": "STOP command accepted. Bot is disconnecting.",
                "login": login_str
            }), 200

        if command in ["START", "RUN"]:
            if active_trading_nodes.get(login_str, False):
                return jsonify({
                    "status": "success",
                    "success": True,
                    "message": "Bot is already actively trading for this account.",
                    "login": login_str
                }), 200

            active_trading_nodes[login_str] = True

            worker = threading.Thread(
                target=launch_async_worker_thread,
                args=(login_str, mt5_password, mt5_server, mt5_symbol, token_override if token_override else None),
                daemon=True,
                name=f"Worker-{login_str}"
            )
            trading_threads[login_str] = worker
            worker.start()

            return jsonify({
                "status": "success",
                "success": True,
                "message": "START command accepted. Immediate continuous burst trading initiated.",
                "login": login_str,
                "symbol": mt5_symbol
            }), 200

        return jsonify({
            "status": "success",
            "success": True,
            "message": f"Command '{command}' processed successfully.",
            "login": login_str
        }), 200

    except Exception as err:
        print(f"[UNIVERSAL CONTROLLER ERROR] {err}")
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "success": False,
            "message": f"Server Handler Fault: {str(err)}"
        }), 200

@app.route("/status", methods=["GET", "OPTIONS"])
def status_endpoint():
    active_accounts = [login for login, running in active_trading_nodes.items() if running]
    return jsonify({
        "status": "online",
        "active_accounts": active_accounts
    }), 200

# ============================================================
# PRODUCTION SERVER ENTRYPOINT & STANDALONE RUNNER
# ============================================================
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ["--run", "-r", "start"]:
        print("[STANDALONE MODE] Launching direct trading engine from environment variables...")
        login = os.environ.get("MT5_LOGIN")
        password = os.environ.get("MT5_PASSWORD")
        server_name = os.environ.get("MT5_SERVER")
        symbol = os.environ.get("MT5_SYMBOL", "XAUUSDm")
        
        if not (login and password and server_name):
            print("[ERROR] Please set MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER environment variables.")
            sys.exit(1)
            
        active_trading_nodes[str(login)] = True
        asyncio.run(high_frequency_trading_engine(str(login), password, server_name, symbol))
    else:
        port = int(os.environ.get("PORT", "10000"))
        print(f"[PRODUCTION SERVER] Launching server on 0.0.0.0:{port}...")
        serve(app, host="0.0.0.0", port=port, threads=8)
