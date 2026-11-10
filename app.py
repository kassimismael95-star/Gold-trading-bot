import os
import sys
import json
import sqlite3
import asyncio
import threading
import datetime
import traceback
import functools
from collections import deque
from flask import Flask, request, jsonify
from flask_cors import CORS
from metaapi_cloud_sdk import MetaApi
from waitress import serve

print = functools.partial(print, flush=True)

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
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response

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
active_connections = {}

# Fast Execution Parameters
MAX_ALLOWED_SPREAD_PIPS = 35.0     # Wide spread tolerance for Gold volatility
POLL_LATENCY_DELAY = 0.05          # 50ms rapid polling loop
BURST_SPACING_DELAY = 0.08         # 80ms spacing between batch executions

# Connection Timeouts
MAX_CONNECTION_ATTEMPTS = 10
CONNECTION_RETRY_DELAY = 5
SYNC_TIMEOUT_SECONDS = 25
DEPLOY_TIMEOUT_SECONDS = 60
DEPLOY_WAIT_TIMEOUT_SECONDS = 120
BROKER_CONNECT_TIMEOUT_SECONDS = 120
STREAM_CONNECT_TIMEOUT_SECONDS = 60

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
    if not password:
        existing = db_get_credentials(license_key)
        if existing and existing.get("mt5_password"):
            password = existing["mt5_password"]

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
    """, (license_key.upper(), str(login).strip(), password, server, symbol))
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
# METAAPI CLIENT
# ============================================================
def get_metaapi_client(override_token: str = None):
    global metaapi_instance
    token = (override_token or os.environ.get("METAAPI_TOKEN", "")).strip()

    if not token:
        raise ValueError("METAAPI_TOKEN is empty. Set it in Render environment variables.")

    with metaapi_lock:
        if metaapi_instance is None or override_token:
            metaapi_instance = MetaApi(token)

    return metaapi_instance

# ============================================================
# VIDEO-STYLE CAPITAL SCALER (SAME-LOT BATCH BURSTS)
# ============================================================
def calculate_video_dynamic_burst(equity: float, balance: float, confidence_score: int) -> tuple:
    capital = max(equity, balance)
    abs_conf = abs(confidence_score)

    if capital < 4.0:
        count = 2 if abs_conf >= 7 else 1
        return 0.01, count, 0.35
    elif capital < 10.0:
        count = 2 if abs_conf >= 6 else 1
        lot = 0.02 if abs_conf >= 8 else 0.01
        return lot, count, 0.60
    elif capital < 25.0:
        if abs_conf >= 8:
            return 0.02, 4, 1.20
        elif abs_conf >= 5:
            return 0.01, 3, 0.80
        else:
            return 0.01, 2, 0.60
    elif capital < 70.0:
        count = 5 if abs_conf >= 7 else 3
        return 0.02, count, 2.50
    elif capital < 200.0:
        count = 6 if abs_conf >= 7 else 4
        lot = 0.03 if abs_conf >= 8 else 0.02
        return lot, count, 5.00
    elif capital < 800.0:
        count = 6 if abs_conf >= 6 else 4
        return 0.10, count, 15.00
    elif capital < 2000.0:
        count = 6 if abs_conf >= 6 else 4
        return 0.20, count, 35.00
    elif capital < 5000.0:
        count = 6 if abs_conf >= 6 else 4
        return 0.30, count, 80.00
    elif capital < 15000.0:
        count = 6 if abs_conf >= 6 else 4
        return 0.90, count, 200.00
    elif capital < 50000.0:
        count = 6 if abs_conf >= 6 else 4
        return 2.00, count, 500.00
    else:
        count = 8 if abs_conf >= 6 else 5
        return 3.00, count, 1200.00

# ============================================================
# BUYER / SELLER MICRO-MOMENTUM TRACKER
# ============================================================
class MicroMomentumTracker:
    def __init__(self, capacity=20):
        self.ticks = deque(maxlen=capacity)
        self.candle_open = None
        self.last_minute = None

    def record_tick(self, price: float):
        current_minute = datetime.datetime.now(datetime.timezone.utc).minute
        if self.last_minute != current_minute or self.candle_open is None:
            self.candle_open = price
            self.last_minute = current_minute
        self.ticks.append(price)

    def evaluate(self) -> tuple:
        if len(self.ticks) < 3:
            return "BUY", 6

        score = 0
        latest = self.ticks[-1]

        short_delta = latest - self.ticks[-3]
        if short_delta > 0.05:
            score += 4
        elif short_delta < -0.05:
            score -= 4
        elif short_delta > 0:
            score += 2
        elif short_delta < 0:
            score -= 2

        full_delta = latest - self.ticks[0]
        if full_delta > 0.15:
            score += 3
        elif full_delta < -0.15:
            score -= 3
        elif full_delta > 0:
            score += 1
        elif full_delta < 0:
            score -= 1

        if self.candle_open is not None:
            candle_delta = latest - self.candle_open
            if candle_delta > 0.10:
                score += 3
            elif candle_delta < -0.10:
                score -= 3
            elif candle_delta > 0:
                score += 1
            elif candle_delta < 0:
                score -= 1

        score = max(-10, min(10, score))
        direction = "BUY" if score >= 0 else "SELL"
        return direction, score

# ============================================================
# PARALLEL BATCH DISPATCH & LIQUIDATION
# ============================================================
async def fire_stacked_batch(connection, symbol: str, direction: str, volume: float, count: int, key: str):
    tasks = []
    bot_signature = f"SCALPER [{key}]"
    print(f"[DISPATCH] Firing {count} concurrent {direction} orders on {symbol} @ {volume} lots...")

    for _ in range(count):
        if direction == "BUY":
            tasks.append(connection.create_market_buy_order(
                symbol=symbol,
                volume=volume,
                stop_loss=None,
                take_profit=None,
                options={"comment": bot_signature}
            ))
        else:
            tasks.append(connection.create_market_sell_order(
                symbol=symbol,
                volume=volume,
                stop_loss=None,
                take_profit=None,
                options={"comment": bot_signature}
            ))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    successful = sum(1 for result in results if not isinstance(result, Exception))
    print(f"[DISPATCH COMPLETE] {successful}/{count} {direction} orders filled on {symbol}.")
    return successful

async def purge_entire_basket_instantly(connection, positions):
    close_tasks = [connection.close_position(position["id"]) for position in positions if "id" in position]
    if close_tasks:
        results = await asyncio.gather(*close_tasks, return_exceptions=True)
        successful = sum(1 for result in results if not isinstance(result, Exception))
        print(f"[LIQUIDATOR] Liquidated {successful}/{len(close_tasks)} positions.")

# ============================================================
# EXNESS SYMBOL RESOLVER
# ============================================================
async def resolve_broker_gold_symbol(connection, requested_symbol: str) -> str:
    candidates = [
        requested_symbol,
        "XAUUSDm",
        "XAUUSD",
        "XAUUSDc",
        "XAUUSDr",
        "GOLD"
    ]

    seen = set()
    filtered_candidates = []

    for symbol in candidates:
        if symbol and symbol not in seen:
            seen.add(symbol)
            filtered_candidates.append(symbol)

    for symbol in filtered_candidates:
        try:
            await connection.subscribe_to_market_data(symbol)
            await asyncio.sleep(0.15)
            price = connection.terminal_state.price(symbol)
            if price and (price.get("ask") or price.get("bid")):
                print(f"[SYMBOL VERIFIED] Using verified symbol: '{symbol}'")
                return symbol
        except Exception:
            continue

    await connection.subscribe_to_market_data(requested_symbol)
    return requested_symbol

# ============================================================
# SAFE NON-BLOCKING ACCOUNT DEPLOYMENT & RETRIEVAL
# ============================================================
async def safe_ensure_deployed(account):
    """Safely checks and deploys account without throwing fatal abort exceptions"""
    try:
        curr_state = getattr(account, "state", "")
        if curr_state == "DEPLOYED":
            return True

        print(f"[DEPLOY] Account is in state '{curr_state}'. Initiating deployment...")
        if curr_state != "DEPLOYING":
            try:
                await account.deploy()
            except Exception as d_err:
                print(f"[DEPLOY CALL NOTICE] {d_err}")

        # Wait non-blockingly for deployment to complete
        for _ in range(30):
            try:
                if getattr(account, "state", "") == "DEPLOYED":
                    print("[DEPLOY SUCCESS] Account is DEPLOYED.")
                    return True
            except Exception:
                pass
            await asyncio.sleep(2)

    except Exception as e:
        print(f"[DEPLOY HANDLER NOTICE] {e}")

    return getattr(account, "state", "") == "DEPLOYED"

async def get_or_create_metaapi_account(api, login, password, server):
    login_str = str(login).strip()
    server_str = str(server).strip()

    try:
        accounts = await api.metatrader_account_api.get_accounts()
        matching_accounts = [
            acc for acc in accounts
            if str(getattr(acc, "login", "")).strip() == login_str
        ]

        print(f"[ACCOUNT SEARCH] Found {len(matching_accounts)} matching MetaApi account(s).")

        # 1. Prefer an already deployed account
        for account in matching_accounts:
            if getattr(account, "state", "") == "DEPLOYED":
                print(f"[ACCOUNT BOUND] Reusing active deployed node: {getattr(account, 'id', '')}")
                return account

        # 2. Deploy existing account if undeployed
        for account in matching_accounts:
            print(f"[ACCOUNT DEPLOYING] Deploying existing MetaApi account: {getattr(account, 'id', '')}")
            await safe_ensure_deployed(account)
            return account

    except Exception as error:
        print(f"[ACCOUNT SEARCH NOTICE] {error}")

    # 3. Create new account only if none exist
    print(f"[ACCOUNT CREATE] No matching account found. Creating new MetaApi account for {login_str}...")
    new_acc = await api.metatrader_account_api.create_account({
        "name": f"Node_{login_str}",
        "type": "cloud",
        "login": login_str,
        "password": password,
        "server": server_str,
        "platform": "mt5",
        "magic": 9924102
    })
    await safe_ensure_deployed(new_acc)
    return new_acc

async def connect_metaapi_account(account, login):
    last_error = None
    login_str = str(login).strip()

    # Clean up lingering streaming socket from a previous STOP
    if login_str in active_connections:
        try:
            old_conn = active_connections.pop(login_str, None)
            if old_conn:
                print(f"[CLEANUP] Closing previous socket for {login_str}...")
                await old_conn.close()
        except Exception as e:
            print(f"[CLEANUP NOTICE] {e}")

    for attempt in range(1, MAX_CONNECTION_ATTEMPTS + 1):
        try:
            print(f"[CONNECTION ATTEMPT {attempt}/{MAX_CONNECTION_ATTEMPTS}] Connecting MT5 account {login}...")

            await safe_ensure_deployed(account)

            print(f"[WAITING BROKER] Waiting for MT5 account {login} to connect...")
            try:
                await asyncio.wait_for(account.wait_connected(), timeout=BROKER_CONNECT_TIMEOUT_SECONDS)
            except Exception as wc_err:
                print(f"[WAIT CONNECTED NOTICE] {wc_err}")

            connection = account.get_streaming_connection()
            await asyncio.wait_for(connection.connect(), timeout=STREAM_CONNECT_TIMEOUT_SECONDS)

            try:
                await asyncio.wait_for(
                    connection.wait_synchronized(),
                    timeout=SYNC_TIMEOUT_SECONDS
                )
                print(f"[CORE LIVE & SYNCHRONIZED] Connected account: {login}")
                active_connections[login_str] = connection
                return connection
            except Exception as sync_error:
                print(f"[SYNC NOTICE] Synchronization notice: {sync_error}")
                if attempt == MAX_CONNECTION_ATTEMPTS:
                    active_connections[login_str] = connection
                    return connection
                await asyncio.sleep(CONNECTION_RETRY_DELAY)
                continue

        except Exception as error:
            last_error = error
            print(f"[CONNECTION FAILED] Attempt {attempt}/{MAX_CONNECTION_ATTEMPTS}: {error}")
            if attempt < MAX_CONNECTION_ATTEMPTS:
                await asyncio.sleep(CONNECTION_RETRY_DELAY)

    raise Exception(f"Failed to connect MetaApi account {login} after {MAX_CONNECTION_ATTEMPTS} attempts: {last_error}")

# ============================================================
# VIDEO-STYLE CORE TRADING ENGINE
# ============================================================
async def high_frequency_trading_engine(login, password, server, symbol, key, token=None):
    print(f"[VIDEO-STYLE ENGINE INITIALIZED] Starting trading loop for {login}...")

    account = None
    connection = None
    tracker = MicroMomentumTracker()

    def update_telemetry(connected, sym, bal=0, eq=0, f_margin=0, m_level=0, pnl=0, open_count=0, price_obj=None, conf=0, err=None):
        telemetry_dict = {
            "connected_to_broker": connected,
            "balance": bal,
            "equity": eq,
            "free_margin": f_margin,
            "margin_level": m_level,
            "floating_pnl": round(pnl, 2),
            "open_positions_count": open_count,
            "active_symbol": sym,
            "confidence_score": conf,
            "symbol_price": price_obj or {},
            "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        if err:
            telemetry_dict["error"] = err
        live_account_telemetry[str(login)] = telemetry_dict

    update_telemetry(False, symbol)

    try:
        api = get_metaapi_client(token)
        account = await get_or_create_metaapi_account(api, login, password, server)
        connection = await connect_metaapi_account(account, login)
        active_symbol = await resolve_broker_gold_symbol(connection, symbol)

        terminal_state = connection.terminal_state
        print(f"[CORE LIVE] Engine trading active on {active_symbol}!")

        while active_trading_nodes.get(str(login), False):
            try:
                account_info = terminal_state.account_information or {}
                equity = float(account_info.get("equity", 0) or 0)
                balance = float(account_info.get("balance", 0) or 0)
                free_margin = float(account_info.get("freeMargin", 0) or 0)
                margin_level = float(account_info.get("marginLevel", 0) or 0)

                broker_connected = getattr(terminal_state, "connected", True)
                price = terminal_state.price(active_symbol)

                if not price or not price.get("bid"):
                    await connection.subscribe_to_market_data(active_symbol)
                    update_telemetry(broker_connected, active_symbol, balance, equity, free_margin, margin_level)
                    await asyncio.sleep(0.1)
                    continue

                current_ask = float(price.get("ask", 0) or 0)
                current_bid = float(price.get("bid", 0) or 0)
                mid_price = (current_ask + current_bid) / 2.0
                tracker.record_tick(mid_price)

                positions = terminal_state.positions or []
                symbol_positions = [
                    position for position in positions
                    if position.get("symbol") == active_symbol
                ]

                net_floating_profit = equity - balance
                direction, confidence = tracker.evaluate()

                update_telemetry(
                    connected=broker_connected,
                    sym=active_symbol,
                    bal=balance,
                    eq=equity,
                    f_margin=free_margin,
                    m_level=margin_level,
                    pnl=net_floating_profit,
                    open_count=len(symbol_positions),
                    price_obj={"ask": current_ask, "bid": current_bid},
                    conf=confidence
                )

                lot_size, burst_count, profit_target = calculate_video_dynamic_burst(
                    equity, balance, confidence
                )

                # ----------------------------------------------------
                # 1. INSTANT BASKET PROFIT TRAPPING (VIDEO BEHAVIOR)
                # ----------------------------------------------------
                if len(symbol_positions) > 0:
                    if net_floating_profit >= profit_target:
                        print(
                            f"[PROFIT TRAPPED] Reached +{net_floating_profit:.2f} USD "
                            f"(Target: {profit_target:.2f} USD). Liquidating basket!"
                        )
                        await purge_entire_basket_instantly(connection, symbol_positions)
                        await asyncio.sleep(BURST_SPACING_DELAY)
                        continue

                    # Safety Drawdown Cutoff
                    if balance > 10.0 and net_floating_profit < -(balance * 0.35):
                        print(
                            f"[CIRCUIT BREAKER] Drawdown cutoff reached: "
                            f"-{abs(net_floating_profit):.2f} USD"
                        )
                        await purge_entire_basket_instantly(connection, symbol_positions)
                        await asyncio.sleep(0.5)
                        continue

                # ----------------------------------------------------
                # 2. IMMEDIATE NEW BATCH DISPATCH (ZERO IDLE TIME)
                # ----------------------------------------------------
                if len(symbol_positions) == 0:
                    current_spread_pips = round((current_ask - current_bid) / 0.1, 2)
                    if current_spread_pips <= MAX_ALLOWED_SPREAD_PIPS:
                        print(
                            f"[IMMEDIATE TRIGGER] Confidence: {confidence} | "
                            f"Dispatching {burst_count}x {direction} @ {lot_size} lots on {active_symbol}..."
                        )
                        await fire_stacked_batch(
                            connection,
                            active_symbol,
                            direction,
                            lot_size,
                            burst_count,
                            key
                        )
                        await asyncio.sleep(BURST_SPACING_DELAY)
                        continue

            except Exception as loop_error:
                print(f"[CYCLE ERROR] {loop_error}")
                await asyncio.sleep(0.5)

            await asyncio.sleep(POLL_LATENCY_DELAY)

    except Exception as error:
        err_msg = str(error)
        print(f"[CRITICAL ENGINE ERROR] Failed to run account {login}: {err_msg}")
        traceback.print_exc()
        update_telemetry(False, symbol, err=err_msg)

    finally:
        active_trading_nodes.pop(str(login), None)
        trading_threads.pop(str(login), None)
        if str(login) in active_connections:
            try:
                old_conn = active_connections.pop(str(login), None)
                if old_conn:
                    await old_conn.close()
            except Exception:
                pass
        if str(login) in live_account_telemetry:
            live_account_telemetry[str(login)]["connected_to_broker"] = False
        print(f"[ENGINE STOPPED] Worker terminated cleanly for: {login}")

def launch_async_worker_thread(login, password, server, symbol, key, token=None):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            high_frequency_trading_engine(login, password, server, symbol, key, token)
        )
    except Exception as error:
        print(f"[THREAD ERROR] {error}")
    finally:
        try:
            loop.close()
        except Exception:
            pass

# ============================================================
# API CONTROLLER & MATCHING ROUTES
# ============================================================
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
def health_root():
    return jsonify({
        "status": "online",
        "service": "Gold Scalper AI Video-Style Engine",
        "mode": "Zero-Idle Micro-Momentum Trapping"
    }), 200

@app.route("/health", methods=["GET"])
@app.route("/ping", methods=["GET"])
def health_ping():
    return jsonify({
        "status": "healthy",
        "service": "Gold Scalper Engine",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }), 200

@app.route("/api/account", methods=["GET"])
@app.route("/get_credentials", methods=["GET"])
def get_account_metadata():
    license_key = request.args.get("license_key", "").strip().upper()
    if license_key in ALLOWED_LICENSES:
        credentials = db_get_credentials(license_key)
        if credentials:
            return jsonify({
                "status": "success",
                "account": {
                    "mt5_login": credentials["mt5_login"],
                    "mt5_server": credentials["mt5_server"],
                    "mt5_symbol": credentials["mt5_symbol"],
                    "has_stored_password": bool(credentials["mt5_password"])
                }
            }), 200
    return jsonify({"status": "not_found"}), 200

@app.route("/status", methods=["GET", "OPTIONS"])
@app.route("/api/status", methods=["GET", "OPTIONS"])
def status_endpoint():
    active_accounts = [
        login for login, running in active_trading_nodes.items() if running
    ]
    return jsonify({
        "status": "online",
        "active_nodes_count": len(active_accounts),
        "active_accounts": active_accounts,
        "telemetry": live_account_telemetry
    }), 200

@app.route("/api/connection-status", methods=["GET", "OPTIONS"])
def connection_status_endpoint():
    login = request.args.get("mt5_login", "").strip()
    return jsonify(live_account_telemetry.get(login, {"connected_to_broker": False})), 200

@app.route("/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/start", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/start", methods=["GET", "POST", "OPTIONS"])
def control_dispatcher():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        data = extract_request_data(request)

        command = str(
            data.get("command") or
            data.get("action") or
            "START"
        ).strip().upper()

        license_key = str(
            data.get("license_key") or
            data.get("key") or
            "BOSSMODE99"
        ).strip().upper()

        if license_key not in ALLOWED_LICENSES:
            return jsonify({
                "status": "error",
                "success": False,
                "message": "Invalid License Key. Allowed keys: BOSSMODE98, BOSSMODE99."
            }), 200

        mt5_login = str(
            data.get("mt5_login") or
            data.get("login") or
            data.get("account") or
            ""
        ).strip()

        mt5_password = str(
            data.get("mt5_password") or
            data.get("password") or
            data.get("pass") or
            ""
        ).strip()

        mt5_server = str(
            data.get("mt5_server") or
            data.get("server") or
            data.get("broker") or
            ""
        ).strip()

        mt5_symbol = str(
            data.get("mt5_symbol") or
            data.get("symbol") or
            "XAUUSDm"
        ).strip()

        saved_credentials = db_get_credentials(license_key)
        if saved_credentials:
            mt5_login = mt5_login or saved_credentials["mt5_login"]
            mt5_password = mt5_password or saved_credentials["mt5_password"]
            mt5_server = mt5_server or saved_credentials["mt5_server"]
            mt5_symbol = mt5_symbol or saved_credentials["mt5_symbol"]

        if command == "SAVE":
            if not mt5_login or not mt5_server:
                return jsonify({
                    "status": "error",
                    "message": "Login and Server are required to save."
                }), 200

            db_save_credentials(license_key, mt5_login, mt5_password, mt5_server, mt5_symbol)
            return jsonify({
                "status": "success",
                "message":
