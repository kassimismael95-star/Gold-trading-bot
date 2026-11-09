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
# CORS HEADERS
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

# Fixed MetaApi account node from previous successful binding
FIXED_METAAPI_ACCOUNT_ID = "28ecb0a9-55bf-4bd4-9d8c-cbc62b8c45ef"

metaapi_instance = None
metaapi_lock = threading.Lock()

active_trading_nodes = {}
trading_threads = {}
live_account_telemetry = {}

# Execution Tuners
MAX_ALLOWED_SPREAD_PIPS = 35.0   # Tolerant spread for Gold volatility
POLL_LATENCY_DELAY = 0.05        # 50ms rapid evaluation loop
BURST_SPACING_DELAY = 0.08       # Rapid dispatch between concurrent batch orders

# Connection Settings
MAX_CONNECTION_ATTEMPTS = 15
CONNECTION_RETRY_DELAY = 5
SYNC_TIMEOUT_SECONDS = 30
DEPLOY_TIMEOUT_SECONDS = 60
DEPLOY_WAIT_TIMEOUT_SECONDS = 180
BROKER_CONNECT_TIMEOUT_SECONDS = 180
STREAM_CONNECT_TIMEOUT_SECONDS = 60
RECONNECT_DELAY = 5

# ============================================================
# SQLITE CREDENTIAL PERSISTENCE
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
        INSERT INTO user_credentials
        (license_key, mt5_login, mt5_password, mt5_server, mt5_symbol, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(license_key) DO UPDATE SET
            mt5_login=excluded.mt5_login,
            mt5_password=excluded.mt5_password,
            mt5_server=excluded.mt5_server,
            mt5_symbol=excluded.mt5_symbol,
            updated_at=CURRENT_TIMESTAMP
    """, (
        license_key.upper(),
        str(login).strip(),
        str(password),
        str(server).strip(),
        str(symbol).strip()
    ))
    conn.commit()
    conn.close()

def db_get_credentials(license_key):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT mt5_login, mt5_password, mt5_server, mt5_symbol FROM user_credentials WHERE license_key = ?",
        (license_key.upper(),)
    )
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
# METAAPI CLIENT FACTORY
# ============================================================
def get_metaapi_client(override_token=None):
    global metaapi_instance
    token = (override_token or METAAPI_TOKEN).strip()
    if not token:
        raise ValueError("METAAPI_TOKEN is missing. Provide it in Render environment variables.")
    with metaapi_lock:
        if metaapi_instance is None or override_token:
            metaapi_instance = MetaApi(token)
    return metaapi_instance

# ============================================================
# EXACT VIDEO CAPITAL SCALER (SAME-LOT BATCH BURSTS)
# ============================================================
def calculate_video_dynamic_burst(equity: float, balance: float, confidence_score: int) -> tuple:
    """
    Evaluates account capital and returns: (lot_size, burst_count, profit_target_usd)
    Matches the exact video scaling progression from micro to multi-lot waves.
    """
    capital = max(equity, balance)
    abs_conf = abs(confidence_score)

    if capital < 4.0:
        # Ultra-Micro Mode (e.g. 0.92 starting capital in video)
        count = 2 if abs_conf >= 7 else 1
        return 0.01, count, 0.35

    elif capital < 10.0:
        # $4.00 - $9.99
        count = 2 if abs_conf >= 6 else 1
        lot = 0.02 if abs_conf >= 8 else 0.01
        return lot, count, 0.60

    elif capital < 25.0:
        # $10.00 - $24.99 (Seen in video at $12.36 entering 0.01 batches)
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
# RAPID MICRO-MOMENTUM ENGINE
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
        Returns: (bias: "BUY"|"SELL", confidence_score: int from -10 to +10)
        """
        if len(self.ticks) < 3:
            return "BUY", 6  # immediate default entry

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

        # 2. Window Velocity (across full sample deque)
        full_delta = latest - self.ticks[0]
        if full_delta > 0.15:
            score += 3
        elif full_delta < -0.15:
            score -= 3
        elif full_delta > 0:
            score += 1
        elif full_delta < 0:
            score -= 1

        # 3. Micro-Candle Spread
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
# PARALLEL BATCH DISPATCH & INSTANT BASKET FLUSH
# ============================================================
async def fire_stacked_batch(connection, symbol: str, direction: str, volume: float, count: int, key: str):
    tasks = []
    comment = f"SCALPER [{key}]"
    print(f"[DISPATCH] Firing {count} concurrent {direction} orders on {symbol} @ {volume} lots...")

    for _ in range(count):
        if direction == "BUY":
            tasks.append(connection.create_market_buy_order(
                symbol=symbol,
                volume=volume,
                stop_loss=None,
                take_profit=None,
                options={"comment": comment}
            ))
        else:
            tasks.append(connection.create_market_sell_order(
                symbol=symbol,
                volume=volume,
                stop_loss=None,
                take_profit=None,
                options={"comment": comment}
            ))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    success = sum(1 for r in results if not isinstance(r, Exception))
    print(f"[DISPATCH COMPLETE] {success}/{count} {direction} orders filled.")
    return success

async def purge_entire_basket(connection, positions):
    """Instantly closes all open positions in parallel"""
    tasks = [connection.close_position(p["id"]) for p in positions if "id" in p]
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        success = sum(1 for r in results if not isinstance(r, Exception))
        print(f"[BASKET FLUSH] Liquidated {success}/{len(tasks)} open positions.")

# ============================================================
# SYMBOL RESOLUTION
# ============================================================
async def resolve_gold_symbol(connection, requested_symbol: str) -> str:
    requested_symbol = str(requested_symbol or "").strip()
    candidates = [
        requested_symbol,
        "XAUUSDm",
        "XAUUSD",
        "XAUUSDc",
        "XAUUSDr",
        "GOLD"
    ]
    seen = set()
    for s in candidates:
        if s and s not in seen:
            seen.add(s)
            try:
                await connection.subscribe_to_market_data(s)
                await asyncio.sleep(0.20)
                p = connection.terminal_state.price(s)
                if p and (p.get("ask") or p.get("bid")):
                    print(f"[SYMBOL VERIFIED] Active trading symbol: '{s}'")
                    return s
            except Exception:
                continue
    return requested_symbol

# ============================================================
# ACCOUNT BINDING & TIMEOUT-PROTECTED CONNECTION
# ============================================================
async def get_or_create_account(api, login: str, password: str, server: str):
    login_str = str(login).strip()
    server_str = str(server).strip()

    # 1. Try fixed account ID first
    try:
        account = await api.metatrader_account_api.get_account(FIXED_METAAPI_ACCOUNT_ID)
        if getattr(account, "login", "") == login_str:
            if getattr(account, "state", "") != "DEPLOYED":
                await asyncio.wait_for(account.deploy(), timeout=DEPLOY_TIMEOUT_SECONDS)
                await asyncio.wait_for(account.wait_deployed(), timeout=DEPLOY_WAIT_TIMEOUT_SECONDS)
            print(f"[ACCOUNT BOUND] Reusing fixed MetaApi account: {FIXED_METAAPI_ACCOUNT_ID}")
            return account
    except Exception as e:
        print(f"[BINDING NOTICE] Fixed ID unavailable ({e}), searching existing accounts...")

    # 2. Search all existing accounts on this MetaApi token
    try:
        accounts = await api.metatrader_account_api.get_accounts()
        for acc in accounts:
            if str(getattr(acc, "login", "")).strip() == login_str:
                if getattr(acc, "state", "") != "DEPLOYED":
                    await asyncio.wait_for(acc.deploy(), timeout=DEPLOY_TIMEOUT_SECONDS)
                    await asyncio.wait_for(acc.wait_deployed(), timeout=DEPLOY_WAIT_TIMEOUT_SECONDS)
                print(f"[ACCOUNT BOUND] Reusing matching MetaApi account: {getattr(acc, 'id', '')}")
                return acc
    except Exception:
        pass

    # 3. Create fresh account if none exists
    print(f"[ACCOUNT CREATE] Creating new MetaApi account for {login_str}...")
    new_acc = await api.metatrader_account_api.create_account({
        "name": f"Node_{login_str}",
        "type": "cloud",
        "login": login_str,
        "password": password,
        "server": server_str,
        "platform": "mt5",
        "magic": 9924102
    })
    await asyncio.wait_for(new_acc.deploy(), timeout=DEPLOY_TIMEOUT_SECONDS)
    await asyncio.wait_for(new_acc.wait_deployed(), timeout=DEPLOY_WAIT_TIMEOUT_SECONDS)
    return new_acc

async def connect_streaming(account, login: str):
    for attempt in range(1, MAX_CONNECTION_ATTEMPTS + 1):
        try:
            print(f"[CONNECTION ATTEMPT {attempt}/{MAX_CONNECTION_ATTEMPTS}] Connecting {login}...")
            if getattr(account, "state", "") != "DEPLOYED":
                await asyncio.wait_for(account.deploy(), timeout=DEPLOY_TIMEOUT_SECONDS)
                await asyncio.wait_for(account.wait_deployed(), timeout=DEPLOY_WAIT_TIMEOUT_SECONDS)

            await asyncio.wait_for(account.wait_connected(), timeout=BROKER_CONNECT_TIMEOUT_SECONDS)
            connection = account.get_streaming_connection()
            await asyncio.wait_for(connection.connect(), timeout=STREAM_CONNECT_TIMEOUT_SECONDS)

            try:
                await asyncio.wait_for(connection.wait_synchronized(), timeout=SYNC_TIMEOUT_SECONDS)
            except Exception:
                print("[SYNC NOTICE] Proceeding with unsynchronized stream.")

            print(f"[CORE LIVE & SYNCHRONIZED] Connected to MT5 account: {login}")
            return connection
        except Exception as err:
            print(f"[CONNECTION FAILED] Attempt {attempt}: {err}")
            if attempt < MAX_CONNECTION_ATTEMPTS:
                await asyncio.sleep(CONNECTION_RETRY_DELAY)
    raise Exception(f"Failed to connect account {login} after {MAX_CONNECTION_ATTEMPTS} attempts.")

# ============================================================
# CORE VIDEO-STYLE CONTINUOUS TRADING ENGINE
# ============================================================
async def video_style_trading_engine(login, password, server, symbol, key, token=None):
    print(f"[ENGINE INITIALIZED] Starting Video-Style Scalper for {login}...")

    tracker = MicroMomentumTracker()

    def push_telemetry(connected, sym, bal=0, eq=0, f_margin=0, m_level=0, pnl=0, open_count=0, price_obj=None, conf=0):
        live_account_telemetry[str(login)] = {
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

    push_telemetry(False, symbol)

    try:
        api = get_metaapi_client(token)
        account = await get_or_create_account(api, login, password, server)
        connection = await connect_streaming(account, login)
        active_symbol = await resolve_gold_symbol(connection, symbol)

        terminal = connection.terminal_state
        print(f"[CORE LIVE] Engine trading live on {active_symbol}!")

        while active_trading_nodes.get(str(login), False):
            try:
                acc_info = terminal.account_information or {}
                equity = float(acc_info.get("equity", 0) or 0)
                balance = float(acc_info.get("balance", 0) or 0)
                free_margin = float(acc_info.get("freeMargin", 0) or 0)
                margin_level = float(acc_info.get("marginLevel", 0) or 0)

                broker_connected = getattr(terminal, "connected", True)
                price_data = terminal.price(active_symbol)

                if not price_data or not price_data.get("bid"):
                    await connection.subscribe_to_market_data(active_symbol)
                    push_telemetry(broker_connected, active_symbol, balance, equity, free_margin, margin_level)
                    await asyncio.sleep(0.1)
                    continue

                ask = float(price_data.get("ask", 0) or 0)
                bid = float(price_data.get("bid", 0) or 0)
                mid_price = (ask + bid) / 2.0
                tracker.record_tick(mid_price)

                all_positions = terminal.positions or []
                my_positions = [p for p in all_positions if p.get("symbol") == active_symbol]
                net_pnl = equity - balance

                direction, confidence = tracker.evaluate()

                push_telemetry(
                    connected=broker_connected,
                    sym=active_symbol,
                    bal=balance,
                    eq=equity,
                    f_margin=free_margin,
                    m_level=margin_level,
                    pnl=net_pnl,
                    open_count=len(my_positions),
                    price_obj={"ask": ask, "bid": bid},
                    conf=confidence
                )

                lot_size, burst_count, profit_target = calculate_video_dynamic_burst(
                    equity, balance, confidence
                )

                # ========================================================
                # 1. INSTANT BASKET PROFIT TRAPPING (VIDEO BEHAVIOR)
                # ========================================================
                if len(my_positions) > 0:
                    if net_pnl >= profit_target:
                        print(f"[PROFIT TRAPPED] Reached +{net_pnl:.2f} USD (Target: {profit_target:.2f}). Liquidating basket instantly!")
                        await purge_entire_basket(connection, my_positions)
                        await asyncio.sleep(0.08)
                        continue

                    # Safety Hard Drawdown Cutoff (at 35% of balance on larger accounts)
                    if balance > 10.0 and net_pnl < -(balance * 0.35):
                        print(f"[CIRCUIT BREAKER] Hard cutoff reached (-{abs(net_pnl):.2f} USD). Flushing basket.")
                        await purge_entire_basket(connection, my_positions)
                        await asyncio.sleep(0.5)
                        continue

                # ========================================================
                # 2. IMMEDIATE NEW BATCH DISPATCH (ZERO IDLE TIME)
                # ========================================================
                if len(my_positions) == 0:
                    spread_pips = round((ask - bid) / 0.1, 2)
                    if spread_pips <= MAX_ALLOWED_SPREAD_PIPS:
                        print(f"[IMMEDIATE TRIGGER] Confidence: {confidence} | Dispatching {burst_count}x {direction} @ {lot_size} lots...")
                        await fire_stacked_batch(connection, active_symbol, direction, lot_size, burst_count, key)
                        await asyncio.sleep(0.08)
                        continue

            except Exception as cycle_err:
                print(f"[CYCLE EXCEPTION] {cycle_err}")
                await asyncio.sleep(0.5)

            await asyncio.sleep(POLL_LATENCY_DELAY)

    except Exception as fatal:
        print(f"[FATAL ENGINE ERROR] {fatal}")
        traceback.print_exc()
        push_telemetry(False, symbol)
    finally:
        active_trading_nodes.pop(str(login), None)
        trading_threads.pop(str(login), None)
        if str(login) in live_account_telemetry:
            live_account_telemetry[str(login)]["connected_to_broker"] = False
        print(f"[ENGINE STOPPED] Worker terminated for {login}")

def run_worker_thread(login, password, server, symbol, key, token=None):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(video_style_trading_engine(login, password, server, symbol, key, token))
    finally:
        loop.close()

# ============================================================
# API CONTROLLER & ROUTES
# ============================================================
def extract_body(req):
    try:
        return req.get_json(force=True, silent=True) or req.args.to_dict() or {}
    except Exception:
        return req.args.to_dict() or {}

@app.route("/", methods=["GET"])
def health_root():
    return jsonify({
        "status": "online",
        "engine": "Video-Style Momentum Burst Scalper",
        "mode": "Zero-Idle Instant Basket Trapping"
    }), 200

@app.route("/status", methods=["GET", "OPTIONS"])
@app.route("/api/status", methods=["GET", "OPTIONS"])
def get_status():
    active = [k for k, v in active_trading_nodes.items() if v]
    return jsonify({
        "status": "online",
        "active_nodes_count": len(active),
        "active_accounts": active,
        "telemetry": live_account_telemetry
    }), 200

@app.route("/api/connection-status", methods=["GET", "OPTIONS"])
def connection_status():
    login = request.args.get("mt5_login", "").strip()
    return jsonify(live_account_telemetry.get(login, {"connected_to_broker": False})), 200

@app.route("/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/start", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/start", methods=["GET", "POST", "OPTIONS"])
def handle_control():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    data = extract_body(request)
    command = str(data.get("command") or data.get("action") or "START").strip().upper()
    license_key = str(data.get("license_key") or data.get("key") or "BOSSMODE99").strip().upper()

    if license_key not in ALLOWED_LICENSES:
        return jsonify({"status": "error", "message": "Invalid License Key."}), 200

    login = str(data.get("mt5_login") or data.get("login") or "").strip()
    password = str(data.get("mt5_password") or data.get("password") or "").strip()
    server = str(data.get("mt5_server") or data.get("server") or "").strip()
    symbol = str(data.get("mt5_symbol") or data.get("symbol") or "XAUUSDm").strip()

    saved = db_get_credentials(license_key)
    if saved:
        login = login or saved["mt5_login"]
        password = password or saved["mt5_password"]
        server = server or saved["mt5_server"]
        symbol = symbol or saved["mt5_symbol"]

    if command == "STOP":
        active_trading_nodes[str(login)] = False
        print(f"[STOP DISPATCHED] Terminating scalper for {login}...")
        return jsonify({"status": "success", "message": "Bot stopping."}), 200

    if command in ["START", "RUN"]:
        if not login or not password or not server:
            return jsonify({"status": "error", "message": "Missing MT5 credentials."}), 200

        db_save_credentials(license_key, login, password, server, symbol)

        if active_trading_nodes.get(str(login), False):
            return jsonify({"status": "success", "message": "Bot is already actively trading."}), 200

        active_trading_nodes[str(login)] = True
        token_override = str(data.get("metaapi_token") or "").strip() or None

        worker = threading.Thread(
            target=run_worker_thread,
            args=(login,
