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
# NON-STOP SCALPING PARAMETERS ($10 ACCOUNT OPTIMIZED)
# ============================================================
BURST_ORDER_COUNT = 4          # Safe initial burst count for small balance
MIN_TARGET_PROFIT_USD = 0.50   # Quick micro-target
PROFIT_EQUITY_RATIO = 0.03     # 3% compounding wave target
MAX_ALLOWED_SPREAD_PIPS = 15.0 # High tolerance spread filter
POLL_LATENCY_DELAY = 0.02      # Continuous execution loop

def get_metaapi_client(override_token: str = None):
    global metaapi_instance
    token = (override_token or os.environ.get("METAAPI_TOKEN", "")).strip()
    if not token:
        print("[WARNING] METAAPI_TOKEN is not configured in environment.")
    with metaapi_lock:
        if metaapi_instance is None or override_token:
            metaapi_instance = MetaApi(token)
    return metaapi_instance

def calculate_safe_lot_size(equity: float) -> float:
    """
    Optimized for micro-balances ($10 - $50):
    Forces a safe 0.01 lot size so the broker never rejects orders due to insufficient margin.
    """
    if equity < 30.0:
        return 0.01  # Safe micro-lot for $10 accounts
    elif equity < 100.0:
        return 0.02
    elif equity < 1000.0:
        return 0.10
    else:
        return 0.50

# ============================================================
# CANDLE & TICK MOMENTUM ENGINE
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
            delta = self.ticks[-1] - self.ticks[0]
            return "BUY" if delta >= 0 else "SELL"
            
        return "BUY"

# ============================================================
# DYNAMIC BROKER SYMBOL RESOLVER
# ============================================================
async def resolve_broker_gold_symbol(connection, requested_symbol: str) -> str:
    """Automatically detects the exact Gold symbol suffix used by Exness."""
    candidates = [requested_symbol, "XAUUSDm", "XAUUSD", "GOLD", "XAUUSD.a", "XAUUSD.ecn", "XAUUSD_i"]
    for sym in candidates:
        try:
            await connection.subscribe_to_market_data(sym)
            await asyncio.sleep(0.1)
            price = connection.terminal_state.price(sym)
            if price and (price.get("ask") or price.get("bid")):
                print(f"[SYMBOL RESOLVED] Successfully connected to broker symbol: '{sym}'")
                return sym
        except Exception:
            continue
    print(f"[SYMBOL NOTICE] Falling back to default: {requested_symbol}")
    return requested_symbol

# ============================================================
# EXECUTION & PURGE ENGINES
# ============================================================
async def fire_stacked_directional_burst(connection, symbol: str, direction: str, volume: float, count: int, login: str):
    tasks = []
    print(f"[EXECUTING] Firing {count}x {direction} orders @ {volume} lots on {symbol} for account {login}...")
    for _ in range(count):
        if direction == "BUY":
            tasks.append(connection.create_market_buy_order(symbol, volume, 0, 0))
        else:
            tasks.append(connection.create_market_sell_order(symbol, volume, 0, 0))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    successful = 0
    for r in results:
        if isinstance(r, Exception):
            print(f"[ORDER REJECTED BY BROKER]: {r}")
        else:
            successful += 1

    print(f"[BURST DEPLOYED] {login} -> {successful}/{count} {direction} orders live on {symbol}")

async def purge_entire_basket_instantly(connection, positions):
    close_tasks = [
        connection.close_position(pos["id"])
        for pos in positions
        if "id" in pos
    ]
    if close_tasks:
        results = await asyncio.gather(*close_tasks, return_exceptions=True)
        print(f"[LIQUIDATOR] Purged {len(results)} positions in parallel.")

# ============================================================
# ACCOUNT PROVISIONING
# ============================================================
async def get_or_create_metaapi_account(api, login, password, server):
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
        print(f"[ACCOUNT SEARCH NOTICE] {fetch_err}")

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
# HIGH-FREQUENCY EXECUTION CORE
# ============================================================
async def high_frequency_trading_engine(login, password, server, symbol, token=None):
    print(f"[SYSTEM INITIATED] Connecting active matrix for account {login} on {server}")
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
        
        # Dynamically resolve correct broker symbol suffix (e.g., XAUUSD vs XAUUSDm)
        active_symbol = await resolve_broker_gold_symbol(connection, symbol)
        print(f"[CORE LIVE] Non-Stop Active Scalper running on symbol: {active_symbol}")

        while active_trading_nodes.get(str(login), False):
            account_info = account.account_information or {}
            equity = float(account_info.get("equity", 0) or 0)
            balance = float(account_info.get("balance", 0) or 0)

            terminal_state = connection.terminal_state
            price = terminal_state.price(active_symbol)
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
            symbol_positions = [p for p in positions if p.get("symbol") == active_symbol]
            net_floating_profit = equity - balance

            dynamic_profit_target = max(MIN_TARGET_PROFIT_USD, balance * PROFIT_EQUITY_RATIO)

            # 1. BASKET TAKE-PROFIT PURGE
            if symbol_positions and net_floating_profit >= dynamic_profit_target:
                print(f"[TARGET HIT] Purging: +${net_floating_profit:.2f} >= Target: ${dynamic_profit_target:.2f}")
                await purge_entire_basket_instantly(connection, symbol_positions)
                await asyncio.sleep(0.01)
                continue

            # 2. ZERO-DOWNTIME INSTANT RELOAD
            if len(symbol_positions) == 0:
                direction = candle_tracker.determine_bias()
                assigned_lot = calculate_safe_lot_size(equity if equity > 0 else balance)
                
                print(f"[NON-STOP RELOAD] Firing {direction} cluster on {active_symbol} (Balance: ${balance:.2f}, Lots: {assigned_lot})")
                await fire_stacked_directional_burst(
                    connection, active_symbol, direction, assigned_lot, BURST_ORDER_COUNT, login
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

def launch_async_worker_thread(login, password, server, symbol, token=None):
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

def extract_request_data(req):
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

@app.route("/", methods=["GET", "POST", "OPTIONS"])
@app.route("/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/start", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/start", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/trade", methods=["GET", "POST", "OPTIONS"])
def universal_trade_controller():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok", "message": "Preflight accepted"}), 200

    try:
        data = extract_request_data(request)
        command = str(data.get("command") or data.get("action") or "START").strip().upper()
        
        token_override = str(
            data.get("metaapi_token") or data.get("token") or request.headers.get("Authorization", "")
        ).replace("Bearer ", "").strip()

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

        if not mt5_login or not mt5_password or not mt5_server:
            return jsonify({
                "status": "error",
                "success": False,
                "message": "Missing credentials. Please check input fields."
            }), 200

        login_str = str(mt5_login).strip()

        if command == "STOP":
            active_trading_nodes[login_str] = False
            return jsonify({"status": "success", "success": True, "message": "STOP command accepted."}), 200

        if command in ["START", "RUN"]:
            if active_trading_nodes.get(login_str, False):
                return jsonify({"status": "success", "success": True, "message": "Bot is already running."}), 200

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
                "message": "START command accepted. Trading engine active.",
                "login": login_str,
                "symbol": mt5_symbol
            }), 200

        return jsonify({"status": "success", "success": True, "message": f"Command '{command}' processed."}), 200

    except Exception as err:
        print(f"[UNIVERSAL CONTROLLER ERROR] {err}")
        traceback.print_exc()
        return jsonify({"status": "error", "success": False, "message": str(err)}), 200

@app.route("/status", methods=["GET", "OPTIONS"])
def status_endpoint():
    active_accounts = [login for login, running in active_trading_nodes.items() if running]
    return jsonify({"status": "online", "active_accounts": active_accounts})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    serve(app, host="0.0.0.0", port=port, threads=8)
