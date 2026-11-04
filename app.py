import os, re, sqlite3, asyncio, threading, datetime, traceback
from collections import deque
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from metaapi_cloud_sdk import MetaApi
from waitress import serve

app = Flask(__name__)
# Enable full CORS across all origins and headers for Bolt compatibility
CORS(app, resources={r"/*": {"origins": "*"}})

METAAPI_TOKEN = os.environ.get("METAAPI_TOKEN", "").strip()
ALLOWED_LICENSES = {"BOSSMODE98", "BOSSMODE99"}
DB_PATH = "/tmp/credentials.db"

metaapi_instance = None
metaapi_lock = threading.Lock()
state_lock = threading.RLock()
active_trading_nodes = {}
trading_threads = {}
active_connections = {}
live_account_telemetry = {}
connection_diagnostics = {}

# Scalping Parameters
BURST_ORDER_COUNT = 8
MAX_ALLOWED_SPREAD_PIPS = 20.0
MAX_ACCOUNT_DRAWDOWN_RATIO = 0.25
POLL_LATENCY_DELAY = 0.10        # Faster 100ms polling for micro-spikes
RECONNECT_DELAY_SECONDS = 5
MAX_CONSECUTIVE_TRANSIENT_ERRORS = 2

# ============================================================
# CORS & FORCED JSON HEADERS
# ============================================================
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, HEAD"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, x-api-key, X-Requested-With, Accept"
    response.headers["Content-Type"] = "application/json"
    response.headers["Cache-Control"] = "no-store"
    return response

@app.errorhandler(Exception)
def handle_exception(error):
    if isinstance(error, HTTPException):
        return jsonify({
            "status": "error",
            "success": False,
            "message": error.description,
            "code": error.code
        }), 200

    traceback.print_exc()
    return jsonify({
        "status": "error",
        "success": False,
        "message": str(error)
    }), 200

# ============================================================
# FAIL-SAFE SQLITE STORAGE (/tmp/credentials.db)
# ============================================================
def init_db():
    try:
        with sqlite3.connect(DB_PATH, timeout=15) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS credentials (
                license_key TEXT NOT NULL,
                mt5_login TEXT NOT NULL,
                mt5_password TEXT NOT NULL,
                mt5_server TEXT NOT NULL,
                mt5_symbol TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (license_key, mt5_login)
            )""")
            conn.commit()
    except Exception as e:
        print(f"[DB INIT ERROR] {e}")

init_db()

def db_save_credentials(key, login, password, server, symbol):
    init_db()
    try:
        with sqlite3.connect(DB_PATH, timeout=15) as conn:
            conn.execute("""INSERT INTO credentials
                (license_key,mt5_login,mt5_password,mt5_server,mt5_symbol,updated_at)
                VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(license_key, mt5_login) DO UPDATE SET
                mt5_password=excluded.mt5_password,
                mt5_server=excluded.mt5_server,
                mt5_symbol=excluded.mt5_symbol,
                updated_at=CURRENT_TIMESTAMP""",
                (key.upper(), str(login).strip(), password, server, symbol))
            conn.commit()
    except Exception as e:
        print(f"[DB SAVE ERROR] {e}")

def db_get_credentials(key, login=""):
    init_db()
    try:
        with sqlite3.connect(DB_PATH, timeout=15) as conn:
            if login:
                row = conn.execute("SELECT mt5_login,mt5_password,mt5_server,mt5_symbol FROM credentials WHERE license_key=? AND mt5_login=?",
                                   (key.upper(), str(login).strip())).fetchone()
            else:
                row = conn.execute("SELECT mt5_login,mt5_password,mt5_server,mt5_symbol FROM credentials WHERE license_key=? ORDER BY updated_at DESC LIMIT 1",
                                   (key.upper(),)).fetchone()
        if not row: return None
        return {"mt5_login": row[0], "mt5_password": row[1], "mt5_server": row[2], "mt5_symbol": row[3]}
    except Exception as e:
        print(f"[DB GET ERROR] {e}")
        return None

def safe_error(error):
    msg = str(error)
    if METAAPI_TOKEN: msg = msg.replace(METAAPI_TOKEN, "[REDACTED_TOKEN]")
    msg = re.sub(r"(?i)(password|token|authorization)(\s*[:=]\s*)([^,\s;]+)", r"\1\2[REDACTED]", msg)
    return msg[:1500]

def get_metaapi_client():
    global metaapi_instance
    if not METAAPI_TOKEN:
        raise RuntimeError("METAAPI_TOKEN is missing on Render.")
    with metaapi_lock:
        if metaapi_instance is None:
            metaapi_instance = MetaApi(METAAPI_TOKEN)
    return metaapi_instance

async def get_or_create_account(api, login, password, server):
    account_api = api.metatrader_account_api
    accounts = []
    try:
        if hasattr(account_api, "get_accounts_with_classic_pagination"):
            res = await account_api.get_accounts_with_classic_pagination()
            accounts = res.get("items", []) if isinstance(res, dict) else res
        elif hasattr(account_api, "get_accounts"):
            accounts = await account_api.get_accounts()
    except Exception as e:
        print(f"[ACCOUNT SEARCH] {safe_error(e)}")

    for acc in accounts:
        if str(getattr(acc, "login", "")) == str(login) and getattr(acc, "server", "").lower() == str(server).lower():
            return acc

    return await account_api.create_account({
        "name": f"Gold Scalper {login}", "type": "cloud", "login": str(login),
        "password": password, "server": server, "platform": "mt5", "magic": 9924102
    })

async def resolve_symbol(connection, requested):
    candidates = [requested, "XAUUSDm", "XAUUSD", "XAUUSDc", "XAUUSDr", "GOLD", "XAUUSD247", "XAUUSD.a", "XAUUSD.ecn"]
    for sym in dict.fromkeys(x for x in candidates if x):
        try:
            await connection.subscribe_to_market_data(sym)
            await asyncio.sleep(0.2)
            p = connection.terminal_state.price(sym)
            if p and p.get("ask") is not None and p.get("bid") is not None:
                return sym
        except Exception:
            continue
    return requested or "XAUUSD"

def calculate_dynamic_lot_size(equity, free_margin):
    if equity < 30 or free_margin < 20: return 0.01
    if equity < 100 or free_margin < 50: return 0.02
    if equity < 1000: return 0.10
    if equity < 3500: return 0.50
    if equity < 15000: return 1.00
    if equity < 35000: return 1.50
    return 2.00

async def fire_burst(connection, symbol, direction, volume, count, login, key):
    comment = f"[{key}] GOLD SCALPER"[:25]
    tasks = []
    for _ in range(count):
        if direction == "BUY":
            tasks.append(connection.create_market_buy_order(symbol=symbol, volume=volume, options={"comment": comment}))
        else:
            tasks.append(connection.create_market_sell_order(symbol=symbol, volume=volume, options={"comment": comment}))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return sum(1 for r in results if not isinstance(r, Exception))

async def close_basket(connection, positions):
    tasks = [connection.close_position(p["id"]) for p in positions if p.get("id")]
    await asyncio.gather(*tasks, return_exceptions=True)

# ============================================================
# ADAPTIVE VOLATILITY & CONFIDENCE MOMENTUM TRACKER
# ============================================================
class AdaptiveMarketIntelligence:
    def __init__(self, window=30):
        self.ticks = deque(maxlen=window)
        self.candle_open = None
        self.last_minute = None

    def record_tick(self, price):
        minute = datetime.datetime.now(datetime.timezone.utc).minute
        if minute != self.last_minute or self.candle_open is None:
            self.candle_open = price
            self.last_minute = minute
        self.ticks.append(price)

    def analyze(self):
        """
        Returns:
        - direction: BUY or SELL
        - confidence: 0.0 to 1.0 (conviction of movement)
        - volatility: dynamic range in price units
        """
        if len(self.ticks) < 5 or self.candle_open is None:
            return "BUY", 0.50, 0.50

        # Calculate directional delta
        delta = self.ticks[-1] - self.candle_open
        direction = "BUY" if delta >= 0 else "SELL"

        # Calculate consistency/consensus of ticks
        up_ticks = sum(1 for i in range(1, len(self.ticks)) if self.ticks[i] >= self.ticks[i-1])
        down_ticks = len(self.ticks) - 1 - up_ticks
        
        ratio = max(up_ticks, down_ticks) / max(1, (len(self.ticks) - 1))
        confidence = round(ratio, 2)

        # Volatility: Price spread between high and low over window
        volatility = max(self.ticks) - min(self.ticks)

        return direction, confidence, max(0.20, volatility)

# ============================================================
# HIGH-FREQUENCY TRADING ENGINE (DYNAMIC PROFIT PURGE)
# ============================================================
async def high_frequency_trading_engine(login, password, server, symbol, key):
    login = str(login)
    market_ai = AdaptiveMarketIntelligence(window=30)
    failures = 0

    while active_trading_nodes.get(login, False):
        connection = None
        try:
            live_account_telemetry[str(login)] = {
                "connected_to_broker": False,
                "running": True,
                "status_text": "CONNECTING"
            }
            api = get_metaapi_client()
            account = await get_or_create_account(api, login, password, server)

            if getattr(account, "state", None) != "DEPLOYED":
                await account.deploy()

            await account.wait_connected()
            connection = account.get_streaming_connection()
            active_connections[login] = connection
            await connection.connect()
            await connection.wait_synchronized()

            active_symbol = await resolve_broker_symbol = await resolve_symbol(connection, symbol)
            failures = 0

            # State for dynamic trailing profit
            peak_floating_pnl = 0.0

            while active_trading_nodes.get(login, False):
                state = connection.terminal_state
                info = state.account_information or {}
                positions = state.positions or []

                balance = float(info.get("balance", 0) or 0)
                equity = float(info.get("equity", 0) or 0)
                free_margin = float(info.get("freeMargin", 0) or 0)
                margin_level = float(info.get("marginLevel", 0) or 0)

                price = state.price(active_symbol)
                if not price or price.get("ask") is None or price.get("bid") is None:
                    await connection.subscribe_to_market_data(active_symbol)
                    await asyncio.sleep(0.2)
                    continue

                ask, bid = float(price["ask"]), float(price["bid"])
                mid_price = (ask + bid) / 2.0
                market_ai.record_tick(mid_price)

                direction, confidence, volatility = market_ai.analyze()

                basket = [p for p in positions if p.get("symbol") == active_symbol]
                pnl = equity - balance

                live_account_telemetry[str(login)] = {
                    "connected_to_broker": True,
                    "running": True,
                    "status_text": "CONNECTED",
                    "balance": balance,
                    "equity": equity,
                    "free_margin": free_margin,
                    "margin_level": margin_level,
                    "floating_pnl": round(pnl, 2),
                    "open_positions_count": len(basket),
                    "active_symbol": active_symbol,
                    "confidence": f"{int(confidence*100)}%",
                    "volatility": round(volatility, 2),
                    "symbol_price": {"ask": ask, "bid": bid},
                    "last_error": None
                }

                # 1. RISK DRAWDOWN BREAKER
                if basket and pnl < -(balance * MAX_ACCOUNT_DRAWDOWN_RATIO):
                    print(f"[DRAWDOWN CUTOFF] Account {login} hit risk threshold. Purging basket.")
                    await close_basket(connection, basket)
                    active_trading_nodes[login] = False
                    break

                # 2. ADAPTIVE FAST TAKE-PROFIT & VIRTUAL TRAILING
                if basket:
                    # Update peak profit seen for this basket
                    if pnl > peak_floating_pnl:
                        peak_floating_pnl = pnl

                    # DYNAMIC TAKE-PROFIT FORMULA:
                    # Low Confidence -> Quick micro-scalp ($0.60 - $1.00)
                    # High Confidence + High Volatility -> Scaled compounding target
                    base_target = max(0.60, balance * 0.015)  # Fast base trigger
                    if confidence >= 0.75:
                        dynamic_target = max(base_target * 1.5, balance * 0.035)
                    else:
                        dynamic_target = base_target

                    # Trigger A: Instant dynamic profit hit
                    if pnl >= dynamic_target:
                        print(f"[FAST TP HIT] Purging basket at +${pnl:.2f} (Confidence: {confidence*100}%, Volatility: {volatility:.2f})")
                        await close_basket(connection, basket)
                        peak_floating_pnl = 0.0
                        await asyncio.sleep(0.15)
                        continue

                    # Trigger B: Virtual Trailing Lock (lock in profit if pullback occurs)
                    # If profit touched at least $1.20 and drops by 30% from peak, close immediately
                    if peak_floating_pnl >= 1.20 and pnl <= (peak_floating_pnl * 0.70):
                        print(f"[TRAILING TP] Locked in +${pnl:.2f} from peak +${peak_floating_pnl:.2f}")
                        await close_basket(connection, basket)
                        peak_floating_pnl = 0.0
                        await asyncio.sleep(0.15)
                        continue

                # 3. NON-STOP RELOAD WAVE
                if not basket:
                    peak_floating_pnl = 0.0
                    spread = round((ask - bid) / 0.1, 2)
                    if spread > MAX_ALLOWED_SPREAD_PIPS:
                        await asyncio.sleep(POLL_LATENCY_DELAY)
                        continue

                    lot = calculate_dynamic_lot_size(equity if equity > 0 else balance, free_margin)
                    count = BURST_ORDER_COUNT if free_margin >= 25 else 2

                    await fire_burst(connection, active_symbol, direction, lot, count, login, key)
                    await asyncio.sleep(0.15)
                    continue

                await asyncio.sleep(POLL_LATENCY_DELAY)

        except Exception as error:
            failures += 1
            err_msg = safe_error(error)
            print(f"[ENGINE ERROR] {login}: {err_msg}")
            
            if failures >= MAX_CONSECUTIVE_TRANSIENT_ERRORS:
                active_trading_nodes[login] = False
                live_account_telemetry[str(login)] = {
                    "connected_to_broker": False,
                    "running": False,
                    "status_text": "FAILED",
                    "last_error": f"Connection halted after {failures} attempts: {err_msg}"
                }
                break
        finally:
            if connection is not None:
                try: await connection.close()
                except Exception: pass
            active_connections.pop(login, None)

        if active_trading_nodes.get(login, False):
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)

    active_trading_nodes[login] = False
    trading_threads.pop(login, None)

def launch_worker(login, password, server, symbol, key):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(high_frequency_trading_engine(login, password, server, symbol, key))
    finally:
        try: loop.close()
        except Exception: pass

# ============================================================
# API ENDPOINTS (PURE JSON)
# ============================================================
@app.route("/", methods=["GET"])
def health_root():
    return jsonify({
        "status": "online",
        "service": "Gold Scalper API (Dynamic Momentum Engine)"
    }), 200

@app.route("/health", methods=["GET"])
@app.route("/ping", methods=["GET"])
def health_ping():
    return jsonify({
        "status": "healthy",
        "service": "Gold Scalper Engine",
        "timestamp": datetime.datetime.utcnow().isoformat()
    }), 200

@app.route("/api/connect", methods=["GET", "POST", "OPTIONS"])
def connect_endpoint():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    login = request.args.get("login") or request.args.get("mt5_login") or ""
    if request.is_json:
        body = request.get_json(silent=True) or {}
        login = login or body.get("login") or body.get("mt5_login") or ""

    login_str = str(login).strip()
    is_connected = False

    if login_str and login_str in live_account_telemetry:
        is_connected = live_account_telemetry[login_str].get("connected_to_broker", False)
    elif not login_str:
        active = [l for l, running in active_trading_nodes.items() if running]
        if active and active[0] in live_account_telemetry:
            login_str = active[0]
            is_connected = live_account_telemetry[active[0]].get("connected_to_broker", False)

    return jsonify({
        "success": True,
        "status": "success",
        "connected": is_connected,
        "connected_to_broker": is_connected,
        "login": login_str or "21648212",
        "server": "Exness-MT5Trial",
        "message": "Connected" if is_connected else "Ready to connect"
    }), 200

@app.route("/api/account", methods=["GET", "OPTIONS"])
@app.route("/get_credentials", methods=["GET", "OPTIONS"])
def account_metadata():
    if request.method == "OPTIONS": 
        return jsonify({"status": "ok"}), 200
    
    key = request.args.get("license_key", "BOSSMODE99").strip().upper()
    login = request.args.get("login") or request.args.get("mt5_login") or ""
    
    saved = db_get_credentials(key, login)
    
    login_val = saved["mt5_login"] if saved else "21648212"
    server_val = saved["mt5_server"] if saved else "Exness-MT5Trial"
    symbol_val = saved["mt5_symbol"] if saved else "XAUUSD"

    is_connected = False
    if login_val and login_val in live_account_telemetry:
        is_connected = live_account_telemetry[login_val].get("connected_to_broker", False)

    return jsonify({
        "success": True,
        "status": "success",
        "connected": is_connected,
        "connected_to_broker": is_connected,
        "login": login_val,
        "server": server_val,
        "symbol": symbol_val,
        "mt5_login": login_val,
        "mt5_server": server_val,
        "mt5_symbol": symbol_val,
        "account": {
            "login": login_val,
            "server": server_val,
            "symbol": symbol_val,
            "connected": is_connected
        }
    }), 200

@app.route("/status", methods=["GET", "OPTIONS"])
@app.route("/api/status", methods=["GET", "OPTIONS"])
def status_endpoint():
    if request.method == "OPTIONS": 
        return jsonify({"status": "ok"}), 200
    
    req_login = request.args.get("login") or request.args.get("mt5_login") or ""
    req_login_str = str(req_login).strip()

    active = [l for l, running in active_trading_nodes.items() if running]
    target_login = req_login_str if req_login_str else (active[0] if active else "21648212")

    is_running = target_login in active
    is_connected = False
    balance, equity = 0.0, 0.0
    last_error = None

    if target_login and target_login in live_account_telemetry:
        t = live_account_telemetry[target_login]
        is_connected = t.get("connected_to_broker", False)
        balance = t.get("balance", 0.0)
        equity = t.get("equity", 0.0)
        last_error = t.get("last_error")

    return jsonify({
        "success": True,
        "status": "online",
        "running": is_running,
        "connected": is_connected,
        "connected_to_broker": is_connected,
        "login": target_login,
        "balance": balance,
        "equity": equity,
        "last_error": last_error,
        "active_nodes_count": len(active),
        "telemetry": live_account_telemetry
    }), 200

@app.route("/control", methods=["POST", "OPTIONS"])
@app.route("/api/control", methods=["POST", "OPTIONS"])
def control_dispatcher():
    if request.method == "OPTIONS": 
        return jsonify({"status": "ok"}), 200
    
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    command = str(data.get("command", "START")).strip().upper()
    key = str(data.get("license_key", "BOSSMODE99")).strip().upper()

    if key not in ALLOWED_LICENSES:
        return jsonify({"status": "error", "success": False, "message": "Invalid license key."}), 200

    login = str(data.get("mt5_login", "")).strip()

    if command == "STOP":
        if login:
            active_trading_nodes[login] = False
        else:
            for l in list(active_trading_nodes.keys()):
                active_trading_nodes[l] = False
        return jsonify({"status": "success", "success": True, "message": f"Engine stopped for {login}."}), 200

    password = str(data.get("mt5_password", "")).strip()
    server = str(data.get("mt5_server", "")).strip()
    symbol = str(data.get("mt5_symbol", "XAUUSD")).strip()

    saved = db_get_credentials(key, login)
    if saved:
        login = login or saved["mt5_login"]
        password = password or saved["mt5_password"]
        server = server or saved["mt5_server"]
        symbol = symbol or saved["mt5_symbol"]

    if not login or not password or not server:
        return jsonify({"status": "error", "success": False, "message": "Missing credentials. Enter login, password, and server."}), 200

    db_save_credentials(key, login, password, server, symbol)
    active_trading_nodes[login] = True

    worker = threading.Thread(target=launch_worker, args=(login, password, server, symbol, key),
                              daemon=True, name=f"Worker-{login}")
    trading_threads[login] = worker
    worker.start()

    return jsonify({
        "status": "success",
        "success": True,
        "connected": True,
        "message": f"Deployment started for account {login}."
    }), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    print(f"[STARTUP] Dynamic Momentum Scalper listening on 0.0.0.0:{port}")
    serve(app, host="0.0.0.0", port=port, threads=8)
