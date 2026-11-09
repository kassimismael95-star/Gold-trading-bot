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

# ============================================================
# HYBRID STYLE 1 + STYLE 4 SCALPING PARAMETERS
# ============================================================
BURST_ORDER_COUNT = 8              # Stacked orders per wave
MIN_TARGET_PROFIT_USD = 0.80       # Micro take-profit trigger for sub-$10 accounts
PROFIT_EQUITY_RATIO = 0.04         # 4% basket gain target before flushing all orders
TRAILING_FLUSH_RATIO = 0.70        # Lock in 70% of peak profit on pullback
MAX_ALLOWED_SPREAD_PIPS = 25.0     # Wide spread tolerance for Gold volatility
MAX_ACCOUNT_DRAWDOWN_RATIO = 0.35  # Hard circuit breaker drawdown cutoff
POLL_LATENCY_DELAY = 0.015         # 15ms high-frequency polling interval

# Style 4 Grid Martingale Recovery Parameters
GRID_RECOVERY_DISTANCE_PIPS = 18.0 # Pip divergence before deploying recovery stage
MARTINGALE_LOT_MULTIPLIER = 1.5    # Lot scaling factor per recovery stage
MAX_RECOVERY_STAGES = 3            # Anti-blowout hard cap on recovery stages

# ============================================================
# CONNECTION RETRY SETTINGS
# ============================================================
MAX_CONNECTION_ATTEMPTS = 5
CONNECTION_RETRY_DELAY = 5
SYNC_TIMEOUT_SECONDS = 20

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
# CLIENT & ULTRA-PRECISE LOT SCALER
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

def calculate_dynamic_lot_size(equity: float, balance: float, free_margin: float) -> tuple:
    effective_capital = max(equity, balance)

    if effective_capital < 10.0 or free_margin < 2.0:
        return 0.01, 3 if free_margin < 5.0 else 5
    elif effective_capital < 25.0:
        return 0.01, 6
    elif effective_capital < 70.0:
        return 0.02, 6
    elif effective_capital < 200.0:
        return 0.02, 8
    elif effective_capital < 800.0:
        return 0.10, 8
    elif effective_capital < 2000.0:
        return 0.20, 8
    elif effective_capital < 5000.0:
        return 0.30, 8
    elif effective_capital < 15000.0:
        return 0.90, 8
    elif effective_capital < 50000.0:
        return 2.00, 8
    else:
        return 3.00, 8

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
        "GOLD",
        "XAUUSD247",
        "XAUUSD.a",
        "XAUUSD.ecn"
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
                print(f"[SYMBOL VERIFIED] Using Gold symbol: '{symbol}'")
                return symbol

        except Exception as error:
            print(f"[SYMBOL CHECK FAILED] {symbol}: {error}")
            continue

    await connection.subscribe_to_market_data(requested_symbol)
    return requested_symbol

# ============================================================
# PARALLEL EXECUTION & PURGE ENGINES
# ============================================================
async def fire_stacked_directional_burst(connection, symbol: str, direction: str, volume: float, count: int, key: str):
    tasks = []
    bot_signature = f"GOLD MOBILE EA [{key}]"

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

    print(f"[BURST COMPLETE] {successful}/{count} {direction} orders deployed on {symbol} at {volume} lots.")
    return successful

async def purge_entire_basket_instantly(connection, positions):
    close_tasks = []

    for position in positions:
        if "id" in position:
            close_tasks.append(connection.close_position(position["id"]))

    if close_tasks:
        results = await asyncio.gather(*close_tasks, return_exceptions=True)
        successful = sum(1 for result in results if not isinstance(result, Exception))
        print(f"[LIQUIDATOR] Closed {successful}/{len(close_tasks)} positions.")

# ============================================================
# RESILIENT METAAPI ACCOUNT SELECTOR
# ============================================================
async def get_or_create_metaapi_account(api, login, password, server):
    login_str = str(login).strip()
    server_str = str(server).strip()

    try:
        if hasattr(api.metatrader_account_api, "get_accounts_with_classic_pagination"):
            response = await api.metatrader_account_api.get_accounts_with_classic_pagination()
            accounts = response.get("items", []) if isinstance(response, dict) else response
        elif hasattr(api.metatrader_account_api, "get_accounts"):
            accounts = await api.metatrader_account_api.get_accounts()
        else:
            accounts = []

        matching_accounts = []

        for account in accounts:
            account_login = str(getattr(account, "login", "")).strip()
            account_server = str(getattr(account, "server", "")).strip().lower()

            if account_login == login_str and account_server == server_str.lower():
                matching_accounts.append(account)

        print(f"[ACCOUNT SEARCH] Found {len(matching_accounts)} matching MetaApi account(s).")

        # 1. Reuse an already deployed and healthy account
        for account in matching_accounts:
            if getattr(account, "state", "") == "DEPLOYED":
                print(f"[ACCOUNT BOUND] Reusing deployed MetaApi node: {getattr(account, 'id', '')}")
                return account

        # 2. Deploy an existing matching account
        for account in matching_accounts:
            if getattr(account, "state", "") != "DEPLOYED":
                print(f"[ACCOUNT DEPLOYING] Deploying existing MetaApi account: {getattr(account, 'id', '')}")

                try:
                    await account.deploy()
                    await account.wait_deployed()
                except Exception as deploy_error:
                    print(f"[DEPLOY WARNING] {deploy_error}")

                return account

    except Exception as error:
        print(f"[ACCOUNT SEARCH NOTICE] {error}")

    # 3. Create a new account only if no matching account exists
    print("[ACCOUNT CREATE] No matching MetaApi account found. Creating new account.")

    return await api.metatrader_account_api.create_account({
        "name": f"Node_{login_str}",
        "type": "cloud",
        "login": login_str,
        "password": password,
        "server": server_str,
        "platform": "mt5",
        "magic": 9924102
    })

# ============================================================
# RESILIENT CONNECTION MANAGER
# ============================================================
async def connect_metaapi_account(account, login):
    last_error = None

    for attempt in range(1, MAX_CONNECTION_ATTEMPTS + 1):
        try:
            print(f"[CONNECTION ATTEMPT {attempt}/{MAX_CONNECTION_ATTEMPTS}] Connecting MT5 account {login}...")

            if getattr(account, "state", "") != "DEPLOYED":
                try:
                    await account.deploy()
                except Exception as deploy_error:
                    print(f"[DEPLOY WARNING] {deploy_error}")

            await account.wait_connected()

            connection = account.get_streaming_connection()
            await connection.connect()

            try:
                await asyncio.wait_for(
                    connection.wait_synchronized(),
                    timeout=SYNC_TIMEOUT_SECONDS
                )
                print(f"[CORE LIVE & SYNCHRONIZED] Connected account: {login}")
                return connection

            except Exception as sync_error:
                print(f"[SYNC NOTICE] Synchronization warning on attempt {attempt}: {sync_error}")

                if attempt == MAX_CONNECTION_ATTEMPTS:
                    print("[SYNC WARNING] Continuing with unsynchronized connection.")
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
# HIGH-FREQUENCY MOMENTUM TRACKER
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
        if len(self.ticks) < 4:
            return "BUY"

        recent_delta = self.ticks[-1] - self.ticks[-4]
        overall_delta = self.ticks[-1] - self.ticks[0]
        candle_delta = (self.ticks[-1] - self.candle_open) if self.candle_open else 0.0

        score = 0

        if recent_delta > 0:
            score += 2
        elif recent_delta < 0:
            score -= 2

        if overall_delta > 0:
            score += 1
        elif overall_delta < 0:
            score -= 1

        if candle_delta > 0:
            score += 1
        elif candle_delta < 0:
            score -= 1

        return "BUY" if score >= 0 else "SELL"

# ============================================================
# TRADING ENGINE (HYBRID STYLE 1 + STYLE 4)
# ============================================================
async def high_frequency_trading_engine(login, password, server, symbol, key, token=None):
    print(f"[HYBRID ENGINE INITIALIZED] Connecting account {login} on {server}...")

    account = None
    connection = None
    candle_tracker = InstantCandleTracker()
    current_stage = 1
    last_burst_entry_price = 0.0
    active_burst_direction = "BUY"
    peak_basket_profit = 0.0
    consecutive_errors = 0

    live_account_telemetry[str(login)] = {
        "connected_to_broker": False,
        "balance": 0,
        "equity": 0,
        "free_margin": 0,
        "margin_level": 0,
        "floating_pnl": 0,
        "open_positions_count": 0,
        "active_symbol": symbol,
        "active_stage": 1,
        "symbol_price": {},
        "last_updated": datetime.datetime.utcnow().isoformat()
    }

    try:
        api = get_metaapi_client(token)
        account = await get_or_create_metaapi_account(api, login, password, server)

        connection = await connect_metaapi_account(account, login)

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
                symbol_positions = [
                    position for position in positions
                    if position.get("symbol") == active_symbol
                ]

                net_floating_profit = equity - balance

                live_account_telemetry[str(login)] = {
                    "connected_to_broker": True,
                    "balance": balance,
                    "equity": equity,
                    "free_margin": free_margin,
                    "margin_level": margin_level,
                    "floating_pnl": round(net_floating_profit, 2),
                    "open_positions_count": len(symbol_positions),
                    "active_symbol": active_symbol,
                    "active_stage": current_stage,
                    "symbol_price": {
                        "ask": current_ask,
                        "bid": current_bid
                    },
                    "last_updated": datetime.datetime.utcnow().isoformat()
                }

                # ----------------------------------------------------
                # 1. HARD SAFETY CIRCUIT BREAKER
                # ----------------------------------------------------
                max_drawdown_limit = balance * MAX_ACCOUNT_DRAWDOWN_RATIO

                if symbol_positions and net_floating_profit < -max_drawdown_limit:
                    print(
                        f"[CIRCUIT BREAKER] Drawdown limit reached: "
                        f"-{abs(net_floating_profit):.2f} USD"
                    )

                    await purge_entire_basket_instantly(connection, symbol_positions)

                    current_stage = 1
                    peak_basket_profit = 0.0
                    last_burst_entry_price = 0.0

                    await asyncio.sleep(2.0)
                    continue

                # ----------------------------------------------------
                # 2. COMBINED BASKET TAKE-PROFIT PURGE
                # ----------------------------------------------------
                if symbol_positions:
                    if net_floating_profit > peak_basket_profit:
                        peak_basket_profit = net_floating_profit

                    dynamic_target = max(
                        MIN_TARGET_PROFIT_USD,
                        balance * PROFIT_EQUITY_RATIO
                    )

                    if balance < 10.0:
                        dynamic_target = max(0.50, balance * 0.12)

                    if net_floating_profit >= dynamic_target:
                        print(
                            f"[TARGET HIT] Profit {net_floating_profit:.2f} USD "
                            f"reached target {dynamic_target:.2f} USD."
                        )

                        await purge_entire_basket_instantly(connection, symbol_positions)

                        current_stage = 1
                        peak_basket_profit = 0.0
                        last_burst_entry_price = 0.0
                        consecutive_errors = 0

                        await asyncio.sleep(0.05)
                        continue

                    if peak_basket_profit >= 1.50 and net_floating_profit <= (
                        peak_basket_profit * TRAILING_FLUSH_RATIO
                    ):
                        print(
                            f"[TRAILING FLUSH] Securing profit: "
                            f"{net_floating_profit:.2f} USD"
                        )

                        await purge_entire_basket_instantly(connection, symbol_positions)

                        current_stage = 1
                        peak_basket_profit = 0.0
                        last_burst_entry_price = 0.0

                        await asyncio.sleep(0.05)
                        continue

                    # ------------------------------------------------
                    # 3. MARTINGALE GRID RECOVERY
                    # ------------------------------------------------
                    if current_stage < MAX_RECOVERY_STAGES and last_burst_entry_price > 0.0:
                        if active_burst_direction == "BUY":
                            pip_divergence = (
                                last_burst_entry_price - current_bid
                            ) / 0.1
                        else:
                            pip_divergence = (
                                current_ask - last_burst_entry_price
                            ) / 0.1

                        if pip_divergence >= GRID_RECOVERY_DISTANCE_PIPS:
                            current_stage += 1

                            base_lot, burst_count = calculate_dynamic_lot_size(
                                equity,
                                balance,
                                free_margin
                            )

                            scaled_lot = round(
                                base_lot * (
                                    MARTINGALE_LOT_MULTIPLIER ** (current_stage - 1)
                                ),
                                2
                            )

                            print(
                                f"[RECOVERY INJECTION] Stage {current_stage}: "
                                f"{burst_count} orders at {scaled_lot} lots."
                            )

                            await fire_stacked_directional_burst(
                                connection,
                                active_symbol,
                                active_burst_direction,
                                scaled_lot,
                                burst_count,
                                key
                            )

                            last_burst_entry_price = mid_price
                            await asyncio.sleep(0.5)
                            continue

                # ----------------------------------------------------
                # 4. INITIAL BURST RELOAD
                # ----------------------------------------------------
                if len(symbol_positions) == 0:
                    current_stage = 1
                    peak_basket_profit = 0.0

                    current_spread_pips = round(
                        (current_ask - current_bid) / 0.1,
                        2
                    )

                    if current_spread_pips > MAX_ALLOWED_SPREAD_PIPS:
                        await asyncio.sleep(POLL_LATENCY_DELAY)
                        continue

                    active_burst_direction = candle_tracker.determine_bias()
                    base_lot, burst_count = calculate_dynamic_lot_size(
                        equity,
                        balance,
                        free_margin
                    )

                    print(
                        f"[BURST DISPATCH] Stage 1: {burst_count} orders "
                        f"at {base_lot} lots, direction {active_burst_direction}."
                    )

                    success_count = await fire_stacked_directional_burst(
                        connection,
                        active_symbol,
                        active_burst_direction,
                        base_lot,
                        burst_count,
                        key
                    )

                    last_burst_entry_price = mid_price

                    if success_count == 0:
                        consecutive_errors += 1

                        if consecutive_errors >= 3:
                            await asyncio.sleep(3.0)
                            consecutive_errors = 0
                    else:
                        consecutive_errors = 0

                    await asyncio.sleep(0.05)
                    continue

            except Exception as loop_error:
                print(f"[CYCLE ERROR] {loop_error}")
                await asyncio.sleep(1.0)

            await asyncio.sleep(POLL_LATENCY_DELAY)

    except Exception as error:
        print(
            f"[CRITICAL ENGINE ERROR] Failed to connect account {login}: {str(error)}"
        )
        traceback.print_exc()

        live_account_telemetry[str(login)] = {
            "connected_to_broker": False,
            "balance": 0,
            "equity": 0,
            "free_margin": 0,
            "margin_level": 0,
            "floating_pnl": 0,
            "open_positions_count": 0,
            "active_symbol": symbol,
            "active_stage": 1,
            "symbol_price": {},
            "last_updated": datetime.datetime.utcnow().isoformat()
        }

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
        loop.run_until_complete(
            high_frequency_trading_engine(
                login,
                password,
                server,
                symbol,
                key,
                token
            )
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
        "service": "Gold Scalper AI Hybrid Engine",
        "mode": "Parallel Burst + Martingale Grid Recovery"
    }), 200

@app.route("/health", methods=["GET"])
@app.route("/ping", methods=["GET"])
def health_ping():
    return jsonify({
        "status": "healthy",
        "service": "Gold Scalper Engine",
        "timestamp": datetime.datetime.utcnow().isoformat()
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

            db_save_credentials(
                license_key,
                mt5_login,
                mt5_password,
                mt5_server,
                mt5_symbol
            )

            return jsonify({
                "status": "success",
                "message": "Credentials saved securely on server database."
            }), 200

        if not mt5_login or not mt5_password or not mt5_server:
            return jsonify({
                "status": "error",
                "success": False,
                "message": "Missing credentials. Enter login, password, and server."
            }), 200

        db_save_credentials(
            license_key,
            mt5_login,
            mt5_password,
            mt5_server,
            mt5_symbol
        )

        login_str = str(mt5_login).strip()

        if command == "STOP":
            active_trading_nodes[login_str] = False

            return jsonify({
                "status": "success",
                "success": True,
                "message": "STOP command accepted."
            }), 200

        if command in ["START", "RUN"]:
            if active_trading_nodes.get(login_str, False):
                return jsonify({
                    "status": "success",
                    "success": True,
                    "message": "Bot is already running."
                }), 200

            active_trading_nodes[login_str] = True

            token_override = str(
                data.get("metaapi_token") or
                data.get("token") or
                request.headers.get("Authorization", "")
            ).replace("Bearer ", "").strip()

            worker = threading.Thread(
                target=launch_async_worker_thread,
                args=(
                    login_str,
                    mt5_password,
                    mt5_server,
                    mt5_symbol,
                    license_key,
                    token_override if token_override else None
                ),
                daemon=True,
                name=f"Worker-{login_str}"
            )

            trading_threads[login_str] = worker
            worker.start()

            return jsonify({
                "status": "success",
                "success": True,
                "message": f"License [{license_key}] Verified. Hybrid scalper active with Exness Gold resolution.",
                "login": login_str,
                "symbol": mt5_symbol
            }), 200

        return jsonify({
            "status": "success",
            "message": f"Command '{command}' processed."
        }), 200

    except Exception as error:
        print(f"[CONTROLLER FAULT] {error}")
        traceback.print_exc()

        return jsonify({
            "status": "error",
            "success": False,
            "message": str(error)
        }), 200

# ============================================================
# PRODUCTION ENTRYPOINT
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    print(f"[STARTUP] Running Gold Scalper AI Server on 0.0.0.0:{port}...")
    serve(app, host="0.0.0.0", port=port, threads=8)
