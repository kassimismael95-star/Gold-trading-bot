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
    """
    Evaluates account capital and returns: (lot_size, burst_count, profit_target_usd)
    Matches the exact video scaling progression from micro to multi-lot waves.
    """
    capital = max(equity, balance)
    abs_conf = abs(confidence_score)

    if capital < 4.0:
        # Sub-$4 Ultra-Micro Mode (e.g. 0.92 starting capital in video)
        count = 2 if abs_conf >= 7 else 1
        return 0.01, count, 0.35

    elif capital < 10.0:
        # $4.00 - $9.99
        count = 2 if abs_conf >= 6 else 1
        lot = 0.02 if abs_conf >= 8 else 0.01
        return lot, count, 0.60

    elif capital < 25.0:
        # $10.00 - $24.99: bursts of 0.01 to 0.02
        if abs_conf >= 8:
            return 0.02, 4, 1.20
        elif abs_conf >= 5:
            return 0.01, 3, 0.80
        else:
            return 0.01, 2, 0.60

    elif capital < 70.0:
        # $25.00 - $69.99 (Seen in video at $32.43 entering 6x 0.02)
        count = 5 if abs_conf >= 7 else 3
        return 0.02, count, 2.50

    elif capital < 200.0:
        # $70.00 - $199.99 (Seen in video at $139.28 entering 6x 0.02)
        count = 6 if abs_conf >= 7 else 4
        lot = 0.03 if abs_conf >= 8 else 0.02
        return lot, count, 5.00

    elif capital < 800.0:
        # $200.00 - $799.99 (Seen in video at $373.07 entering 6x 0.10)
        count = 6 if abs_conf >= 6 else 4
        return 0.10, count, 15.00

    elif capital < 2000.0:
        # $800.00 - $1,999.99 (Seen in video at $1,484.55 entering 6x 0.20)
        count = 6 if abs_conf >= 6 else 4
        return 0.20, count, 35.00

    elif capital < 5000.0:
        # $2,000.00 - $4,999.99 (Seen in video at $2,640.19 entering 6x 0.30)
        count = 6 if abs_conf >= 6 else 4
        return 0.30, count, 80.00

    elif capital < 15000.0:
        # $5,000.00 - $14,999.99 (Seen in video at $6,838.86 entering 6x 0.90)
        count = 6 if abs_conf >= 6 else 4
        return 0.90, count, 200.00

    elif capital < 50000.0:
        # $15,000.00 - $49,999.99 (Seen in video at $24,259.38 entering 6x 2.00)
        count = 6 if abs_conf >= 6 else 4
        return 2.00, count, 500.00

    else:
        # $50,000.00+ Enterprise Tier (Seen in video at $66k-$189k entering 3.00 lots)
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
        """
        Calculates instant buyer vs seller pressure.
        Returns: (direction: "BUY"|"SELL", confidence_score: int from -10 to +10)
        """
        if len(self.ticks) < 3:
            return "BUY", 6

        score = 0
        latest = self.ticks[-1]

        # 1. Immediate Tick Velocity (last 3 ticks)
        short_delta = latest - self.ticks[-3]
        if short_delta > 0.05:
            score += 4
        elif short_delta < -0.05:
            score -= 4
        elif short_delta > 0:
            score += 2
        elif short_delta < 0:
            score -= 2

        # 2. Window Velocity across sample
        full_delta = latest - self.ticks[0]
        if full_delta > 0.15:
            score += 3
        elif full_delta < -0.15:
            score -= 3
        elif full_delta > 0:
            score += 1
        elif full_delta < 0:
            score -= 1

        # 3. Micro-Candle Position
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
    """Instantly closes all open positions in parallel"""
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
# SAFE ACCOUNT SELECTION & CONNECTION
# ============================================================
async def get_existing_metaapi_accounts(api):
    """
    Retrieves MetaApi accounts safely.
    Supports both current SDK versions and older SDK versions.
    """
    try:
        accounts_response = await api.metatrader_account_api.get_accounts_with_infinite_scroll_pagination()

        # Current SDK returns a paginated response containing "items"
        if isinstance(accounts_response, dict):
            accounts = accounts_response.get("items", [])
        else:
            accounts = accounts_response

        if accounts is None:
            accounts = []

        return accounts

    except AttributeError:
        # Fallback for older MetaApi SDK versions
        print("[SDK COMPATIBILITY] Using legacy get_accounts() method...")
        try:
            accounts = await api.metatrader_account_api.get_accounts()
            if isinstance(accounts, dict):
                return accounts.get("items", [])
            return accounts or []
        except Exception as legacy_error:
            print(f"[LEGACY ACCOUNT SEARCH NOTICE] {legacy_error}")
            return []

    except Exception as error:
        print(f"[ACCOUNT SEARCH NOTICE] {error}")
        return []

def extract_account_field(account, field: str, default=""):
    """
    Safely reads a field from either an SDK account object or a dictionary.
    """
    try:
        if isinstance(account, dict):
            return account.get(field, default)
        return getattr(account, field, default)
    except Exception:
        return default

async def get_or_create_metaapi_account(api, login, password, server):
    login_str = str(login).strip()
    server_str = str(server).strip()

    try:
        accounts = await get_existing_metaapi_accounts(api)

        matching_accounts = [
            account for account in accounts
            if str(extract_account_field(account, "login", "")).strip() == login_str
        ]

        print(f"[ACCOUNT SEARCH] Found {len(matching_accounts)} matching MetaApi account(s).")

        # Reuse an already deployed account
        for account in matching_accounts:
            if str(extract_account_field(account, "state", "")).upper() == "DEPLOYED":
                account_id = extract_account_field(account, "id", "")
                print(f"[ACCOUNT BOUND] Reusing deployed MetaApi node: {account_id}")
                return account

        # Deploy existing account if undeployed
        for account in matching_accounts:
            account_id = extract_account_field(account, "id", "")
            print(f"[ACCOUNT DEPLOYING] Deploying existing MetaApi account: {account_id}")

            try:
                await asyncio.wait_for(account.deploy(), timeout=DEPLOY_TIMEOUT_SECONDS)
                await asyncio.wait_for(account.wait_deployed(), timeout=DEPLOY_WAIT_TIMEOUT_SECONDS)
            except Exception as deploy_error:
                print(f"[DEPLOY WARNING] {deploy_error}")

            return account

    except Exception as error:
        print(f"[ACCOUNT SEARCH NOTICE] {error}")

    # Create new account only if none exist
    print("[ACCOUNT CREATE] No matching account found. Creating new MetaApi account.")

    try:
        new_acc = await api.metatrader_account_api.create_account({
            "name": f"Node_{login_str}",
            "type": "cloud",
            "login": login_str,
            "password": password,
            "server": server_str,
            "platform": "mt5",
            "magic": 9924102,
            "reliability": "regular"
        })

        try:
            await asyncio.wait_for(new_acc.deploy(), timeout=DEPLOY_TIMEOUT_SECONDS)
            await asyncio.wait_for(new_acc.wait_deployed(), timeout=DEPLOY_WAIT_TIMEOUT_SECONDS)
        except Exception as deploy_error:
            print(f"[DEPLOY WARNING] {deploy_error}")

        return new_acc

    except Exception as create_error:
        error_text = str(create_error)

        if "top up" in error_text.lower() or "403" in error_text or "Forbidden" in error_text:
            raise Exception(
                "METAAPI BILLING BLOCKED: MetaApi rejected account creation because your MetaApi "
                "balance/quota needs to be topped up. Log in to the MetaApi dashboard, top up or "
                "resolve the account restriction, then press START again."
            )

        raise create_error

async def connect_metaapi_account(account, login):
    last_error = None
    for attempt in range(1, MAX_CONNECTION_ATTEMPTS + 1):
        try:
            print(f"[CONNECTION ATTEMPT {attempt}/{MAX_CONNECTION_ATTEMPTS}] Connecting MT5 account {login}...")

            account_state = str(extract_account_field(account, "state", "")).upper()

            if account_state != "DEPLOYED":
                try:
                    await asyncio.wait_for(account.deploy(), timeout=DEPLOY_TIMEOUT_SECONDS)
                    await asyncio.wait_for(account.wait_deployed(), timeout=DEPLOY_WAIT_TIMEOUT_SECONDS)
                except Exception as deploy_error:
                    print(f"[DEPLOY WARNING] {deploy_error}")

            await asyncio.wait_for(account.wait_connected(), timeout=BROKER_CONNECT_TIMEOUT_SECONDS)

            connection = account.get_streaming_connection()
            await asyncio.wait_for(connection.connect(), timeout=STREAM_CONNECT_TIMEOUT_SECONDS)

            try:
                await asyncio.wait_for(
                    connection.wait_synchronized(),
                    timeout=SYNC_TIMEOUT_SECONDS
                )
                print(f"[CORE LIVE & SYNCHRONIZED] Connected account: {login}")
                return connection
            except Exception as sync_error:
                print(f"[SYNC NOTICE] Synchronization notice on attempt {attempt}: {sync_error}")

                if attempt == MAX_CONNECTION_ATTEMPTS:
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
        telemetry = {
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
            telemetry["error"] = err

        live_account_telemetry[str(login)] = telemetry

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

                    # Hard Safety Drawdown Cutoff
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
        error_text = str(error)
        print(f"[CRITICAL ENGINE ERROR] Failed to run account {login}: {error_text}")
        traceback.print_exc()
        update_telemetry(False, symbol, err=error_text)

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
                "message": "Credentials saved securely on server database."
            }), 200

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
            return jsonify({
                "status": "success",
                "success": True,
                "message": "STOP command accepted. Worker stopping."
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
                "message": f"License [{license_key}] Verified. Video-style scalper active on {mt5_symbol}.",
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
