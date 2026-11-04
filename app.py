import os, re, sqlite3, asyncio, threading, datetime, traceback
from collections import deque
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from metaapi_cloud_sdk import MetaApi
from waitress import serve

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

METAAPI_TOKEN = os.environ.get("METAAPI_TOKEN", "").strip()
ALLOWED_LICENSES = {"BOSSMODE98", "BOSSMODE99"}
DB_PATH = os.environ.get("DB_PATH", "/tmp/credentials.db")

metaapi_instance = None
metaapi_lock = threading.Lock()
state_lock = threading.RLock()
active_trading_nodes = {}
trading_threads = {}
active_connections = {}
live_account_telemetry = {}
connection_diagnostics = {}

# Strategy settings
BURST_ORDER_COUNT = 8
MIN_TARGET_PROFIT_USD = 1.00
PROFIT_EQUITY_RATIO = 0.05
MAX_ALLOWED_SPREAD_PIPS = 20.0
MAX_ACCOUNT_DRAWDOWN_RATIO = 0.25
POLL_LATENCY_DELAY = 0.20
RECONNECT_DELAY_SECONDS = 10
MAX_CONSECUTIVE_TRANSIENT_ERRORS = 5

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, HEAD"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, x-api-key, X-Requested-With, Accept"
    response.headers["Cache-Control"] = "no-store"
    return response

@app.errorhandler(Exception)
def handle_exception(error):
    if isinstance(error, HTTPException):
        return jsonify({"status":"error","success":False,"message":error.description,"code":error.code}), error.code
    traceback.print_exc()
    return jsonify({"status":"error","success":False,"message":"Internal server error. Check Render application logs."}), 200

def init_db():
    with sqlite3.connect(DB_PATH, timeout=15) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS credentials (
            license_key TEXT PRIMARY KEY, mt5_login TEXT NOT NULL,
            mt5_password TEXT NOT NULL, mt5_server TEXT NOT NULL,
            mt5_symbol TEXT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.commit()

def db_save_credentials(key, login, password, server, symbol):
    with sqlite3.connect(DB_PATH, timeout=15) as conn:
        conn.execute("""INSERT INTO credentials
            (license_key,mt5_login,mt5_password,mt5_server,mt5_symbol,updated_at)
            VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(license_key) DO UPDATE SET
            mt5_login=excluded.mt5_login, mt5_password=excluded.mt5_password,
            mt5_server=excluded.mt5_server, mt5_symbol=excluded.mt5_symbol,
            updated_at=CURRENT_TIMESTAMP""",
            (key.upper(), login, password, server, symbol))
        conn.commit()

def db_get_credentials(key):
    with sqlite3.connect(DB_PATH, timeout=15) as conn:
        row = conn.execute("SELECT mt5_login,mt5_password,mt5_server,mt5_symbol FROM credentials WHERE license_key=?",
                           (key.upper(),)).fetchone()
    if not row: return None
    return {"mt5_login":row[0],"mt5_password":row[1],"mt5_server":row[2],"mt5_symbol":row[3]}

init_db()

FATAL_KEYWORDS = (
    "insufficient funds","balance is empty","workloads stopped","workload stopped",
    "billing","payment required","suspended","unauthorized","invalid token",
    "authentication failed","access denied","invalid credentials","not enough balance"
)

def safe_error(error):
    msg = str(error)
    if METAAPI_TOKEN: msg = msg.replace(METAAPI_TOKEN, "[REDACTED_TOKEN]")
    msg = re.sub(r"(?i)(password|token|authorization)(\s*[:=]\s*)([^,\s;]+)",
                 r"\1\2[REDACTED]", msg)
    return msg[:1500]

def diagnose_error(error):
    msg = safe_error(error)
    low = msg.lower()
    if any(x in low for x in FATAL_KEYWORDS) or "402" in low:
        return {"category":"METAAPI_BILLING_OR_AUTH","message":msg,"should_stop":True,
                "action":"Check MetaApi billing/workload status and API token."}
    if "password" in low or "login" in low:
        return {"category":"MT5_AUTHENTICATION","message":msg,"should_stop":True,
                "action":"Verify MT5 login, password and exact broker server."}
    if "symbol" in low or "market data" in low:
        return {"category":"SYMBOL_OR_MARKET_DATA","message":msg,"should_stop":True,
                "action":"Check exact broker Gold symbol and market hours."}
    if "timeout" in low or "timed out" in low:
        return {"category":"CONNECTION_TIMEOUT","message":msg,"should_stop":False,
                "action":"Temporary timeout; retry with delay and inspect MetaApi."}
    if "connection" in low or "network" in low or "socket" in low:
        return {"category":"NETWORK_CONNECTION","message":msg,"should_stop":False,
                "action":"Network issue; retry with delay."}
    if "margin" in low or "volume" in low or "trade is disabled" in low:
        return {"category":"ORDER_OR_ACCOUNT_RESTRICTION","message":msg,"should_stop":True,
                "action":"Check margin, volume limits and broker trading permissions."}
    return {"category":"UNKNOWN_ERROR","message":msg,"should_stop":False,
            "action":"Inspect full Render logs before retrying."}

def record_error(login, error, stage):
    d = diagnose_error(error)
    d.update({"stage":stage,"timestamp":datetime.datetime.now(datetime.timezone.utc).isoformat()})
    connection_diagnostics[str(login)] = d
    print(f"[DIAGNOSTIC] login={login} stage={stage} category={d['category']} error={d['message']}")
    return d

def telemetry(login, **values):
    item = live_account_telemetry.get(str(login), {})
    item.update(values)
    item["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    live_account_telemetry[str(login)] = item

def get_metaapi_client():
    global metaapi_instance
    if not METAAPI_TOKEN:
        raise RuntimeError("METAAPI_TOKEN environment variable is missing in Render.")
    with metaapi_lock:
        if metaapi_instance is None:
            metaapi_instance = MetaApi(METAAPI_TOKEN)
    return metaapi_instance

async def get_or_create_account(api, login, password, server):
    account_api = api.metatrader_account_api
    accounts = []
    try:
        if hasattr(account_api, "get_accounts_with_classic_pagination"):
            result = await account_api.get_accounts_with_classic_pagination()
            accounts = result.get("items", []) if isinstance(result, dict) else result
        elif hasattr(account_api, "get_accounts"):
            accounts = await account_api.get_accounts()
    except Exception as e:
        print(f"[ACCOUNT SEARCH] {safe_error(e)}")
    for acc in accounts:
        if str(getattr(acc,"login","")) == str(login) and str(getattr(acc,"server","")).lower() == str(server).lower():
            return acc
    return await account_api.create_account({
        "name":f"Gold Scalper {login}","type":"cloud","login":str(login),
        "password":password,"server":server,"platform":"mt5","magic":9924102
    })

async def resolve_symbol(connection, requested):
    candidates = [requested,"XAUUSDm","XAUUSD","XAUUSDc","XAUUSDr","GOLD","XAUUSD247","XAUUSD.a","XAUUSD.ecn"]
    for sym in dict.fromkeys(x for x in candidates if x):
        try:
            await connection.subscribe_to_market_data(sym)
            await asyncio.sleep(0.5)
            p = connection.terminal_state.price(sym)
            if p and p.get("ask") is not None and p.get("bid") is not None:
                return sym
        except Exception:
            continue
    raise RuntimeError(f"No live quote found for Gold symbol '{requested}'. Check broker symbol and market hours.")

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
            tasks.append(connection.create_market_buy_order(symbol=symbol,volume=volume,options={"comment":comment}))
        else:
            tasks.append(connection.create_market_sell_order(symbol=symbol,volume=volume,options={"comment":comment}))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    accepted = 0
    for result in results:
        if isinstance(result, Exception): print(f"[ORDER REJECTED] {login}: {safe_error(result)}")
        else: accepted += 1
    print(f"[ORDER BURST] {login} {direction}: accepted {accepted}/{count}")
    return accepted

async def close_basket(connection, positions):
    tasks = [connection.close_position(p["id"]) for p in positions if p.get("id")]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception): print(f"[CLOSE ERROR] {safe_error(result)}")

class InstantCandleTracker:
    def __init__(self):
        self.ticks = deque(maxlen=30)
        self.candle_open = None
        self.last_minute = None
    def record_tick(self, price):
        minute = datetime.datetime.now(datetime.timezone.utc).minute
        if minute != self.last_minute or self.candle_open is None:
            self.candle_open, self.last_minute = price, minute
        self.ticks.append(price)
    def determine_bias(self):
        if not self.ticks or self.candle_open is None: return "BUY"
        if self.ticks[-1] > self.candle_open: return "BUY"
        if self.ticks[-1] < self.candle_open: return "SELL"
        return "BUY"

async def high_frequency_trading_engine(login,password,server,symbol,key):
    login = str(login)
    tracker = InstantCandleTracker()
    failures = 0
    telemetry(login,running=True,connected_to_broker=False,connection_state="CONNECTING",error=None)
    print(f"[ENGINE] Start login={login}, server={server}, symbol={symbol}")

    while active_trading_nodes.get(login,False):
        connection = None
        try:
            telemetry(login,connection_state="CONNECTING",connected_to_broker=False)
            api = get_metaapi_client()
            account = await get_or_create_account(api,login,password,server)
            if getattr(account,"state",None) != "DEPLOYED":
                telemetry(login,connection_state="DEPLOYING")
                await account.deploy()
            telemetry(login,connection_state="WAITING_FOR_MT5")
            await account.wait_connected()
            connection = account.get_streaming_connection()
            active_connections[login] = connection
            await connection.connect()
            await connection.wait_synchronized()
            active_symbol = await resolve_symbol(connection,symbol)
            failures = 0
            connection_diagnostics.pop(login,None)
            telemetry(login,running=True,connected_to_broker=True,connection_state="CONNECTED",
                      active_symbol=active_symbol,error=None,error_category=None)
            print(f"[CONNECTED] {login} {active_symbol}")

            while active_trading_nodes.get(login,False):
                state = connection.terminal_state
                info = state.account_information or {}
                positions = state.positions or []
                balance = float(info.get("balance",0) or 0)
                equity = float(info.get("equity",0) or 0)
                free_margin = float(info.get("freeMargin",0) or 0)
                margin_level = float(info.get("marginLevel",0) or 0)
                price = state.price(active_symbol)
                if not price or price.get("ask") is None or price.get("bid") is None:
                    await connection.subscribe_to_market_data(active_symbol)
                    await asyncio.sleep(0.5)
                    continue
                ask,bid = float(price["ask"]),float(price["bid"])
                tracker.record_tick((ask+bid)/2)
                basket = [p for p in positions if p.get("symbol")==active_symbol]
                pnl = equity-balance
                telemetry(login,running=True,connected_to_broker=True,connection_state="CONNECTED",
                          balance=balance,equity=equity,free_margin=free_margin,margin_level=margin_level,
                          floating_pnl=round(pnl,2),open_positions_count=len(basket),active_symbol=active_symbol,
                          symbol_price={"ask":ask,"bid":bid},error=None)
                if basket and pnl < -(balance*MAX_ACCOUNT_DRAWDOWN_RATIO):
                    print(f"[RISK] Drawdown threshold reached for {login}; closing this bot basket.")
                    await close_basket(connection,basket)
                    active_trading_nodes[login]=False
                    telemetry(login,running=False,connection_state="STOPPED_DRAWDOWN")
                    break
                target = max(MIN_TARGET_PROFIT_USD,balance*PROFIT_EQUITY_RATIO)
                if basket and pnl >= target:
                    print(f"[PROFIT] Target reached {login}: {pnl:.2f}")
                    await close_basket(connection,basket)
                    await asyncio.sleep(0.25)
                    continue
                if not basket:
                    spread = round((ask-bid)/0.1,2)
                    if spread > MAX_ALLOWED_SPREAD_PIPS:
                        await asyncio.sleep(POLL_LATENCY_DELAY)
                        continue
                    direction = tracker.determine_bias()
                    lot = calculate_dynamic_lot_size(equity if equity>0 else balance,free_margin)
                    count = BURST_ORDER_COUNT if free_margin>=25 else 2
                    accepted = await fire_burst(connection,active_symbol,direction,lot,count,login,key)
                    if accepted == 0: print(f"[ORDER WARNING] No orders accepted for {login}")
                    await asyncio.sleep(0.25)
                    continue
                await asyncio.sleep(POLL_LATENCY_DELAY)

        except asyncio.CancelledError:
            raise
        except Exception as error:
            d = record_error(login,error,"TRADING_ENGINE")
            telemetry(login,running=not d["should_stop"],connected_to_broker=False,
                      connection_state="ERROR",error=d["message"],error_category=d["category"])
            if d["should_stop"]:
                active_trading_nodes[login]=False
                print(f"[ENGINE STOP] Non-retryable issue for {login}")
                break
            failures += 1
            if failures >= MAX_CONSECUTIVE_TRANSIENT_ERRORS:
                active_trading_nodes[login]=False
                telemetry(login,running=False,connection_state="STOPPED_AFTER_RETRIES")
                print(f"[ENGINE STOP] Too many connection failures for {login}")
                break
            print(f"[RECONNECT] {login}, attempt {failures}/{MAX_CONSECUTIVE_TRANSIENT_ERRORS}")
        finally:
            if connection is not None:
                try: await connection.close()
                except Exception as e: print(f"[CLEANUP] {safe_error(e)}")
            active_connections.pop(login,None)

        if active_trading_nodes.get(login,False):
            telemetry(login,connection_state="RETRY_WAIT",connected_to_broker=False)
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)

    active_trading_nodes[login]=False
    
    # PRESERVE LAST TELEMETRY & DIAGNOSTICS FOR THE DASHBOARD
    prev = live_account_telemetry.get(login, {})
    prev.update({
        "running": False,
        "connected_to_broker": False,
        "connection_state": "STOPPED",
        "last_stopped_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    })
    live_account_telemetry[login] = prev

    trading_threads.pop(login,None)
    active_connections.pop(login,None)
    print(f"[ENGINE] Worker stopped for {login}")

def launch_worker(login,password,server,symbol,key):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(high_frequency_trading_engine(login,password,server,symbol,key))
    except Exception as e:
        d = record_error(login,e,"WORKER_THREAD")
        telemetry(login,running=False,connected_to_broker=False,connection_state="WORKER_CRASHED",
                  error=d["message"],error_category=d["category"])
        active_trading_nodes[login]=False
        traceback.print_exc()
    finally:
        try: loop.close()
        except Exception: pass
        if trading_threads.get(login) is threading.current_thread():
            trading_threads.pop(login,None)

@app.route("/",methods=["GET"])
def dashboard():
    return jsonify({"status":"online","service":"Gold Scalper Backend API"}), 200

@app.route("/health",methods=["GET"])
def health():
    return jsonify({"status":"online","service":"Gold Mobile EA",
                    "metaapi_token_configured":bool(METAAPI_TOKEN),
                    "utc_time":datetime.datetime.now(datetime.timezone.utc).isoformat()})

@app.route('/api/connect', methods=['POST', 'OPTIONS'])
def connect_mt5():
    if request.method == 'OPTIONS':
        return jsonify({"status": "ok"}), 200
    try:
        data = request.get_json(silent=True) or {}
        login = data.get('login') or data.get('mt5_login')
        server = data.get('server') or data.get('mt5_server')
        
        if not login or not server:
            return jsonify({
                "success": False,
                "error": "Missing login or server credentials."
            }), 200

        return jsonify({
            "success": True, 
            "message": "Connection parameters validated successfully."
        }), 200
    except Exception as e:
        return jsonify({
            "success": False, 
            "error": str(e)
        }), 200

@app.route("/api/account",methods=["GET","OPTIONS"])
@app.route("/get_credentials",methods=["GET","OPTIONS"])
def account_metadata():
    if request.method=="OPTIONS": return jsonify({"status":"ok"})
    key=request.args.get("license_key","").strip().upper()
    if key not in ALLOWED_LICENSES: return jsonify({"status":"error","message":"Invalid license key."}),200
    saved=db_get_credentials(key)
    if not saved: return jsonify({"status":"success","login":"","server":"","symbol":"XAUUSD"})
    return jsonify({"status":"success","login":saved["mt5_login"],"server":saved["mt5_server"],"symbol":saved["mt5_symbol"]})

@app.route("/status",methods=["GET","OPTIONS"])
@app.route("/api/status",methods=["GET","OPTIONS"])
def status():
    if request.method=="OPTIONS": return jsonify({"status":"ok"})
    active=[login for login,running in active_trading_nodes.items() if running]
    return jsonify({
        "status":"online",
        "running":bool(active),
        "active_accounts":active,
        "active_nodes_count":len(active),
        "telemetry":live_account_telemetry,
        "diagnostics":connection_diagnostics
    }), 200

@app.route("/api/diagnostics",methods=["GET"])
def diagnostics():
    key=request.args.get("license_key","").strip().upper()
    login=request.args.get("login","").strip()
    if key not in ALLOWED_LICENSES:
        return jsonify({"status":"error","message":"Valid license_key query parameter required."}),200
    saved=db_get_credentials(key)
    if saved:
        if login and login!=saved["mt5_login"]:
            return jsonify({"status":"error","message":"Login does not match license."}),200
        login=login or saved["mt5_login"]
    return jsonify({"status":"success","login":login or None,
                    "diagnostics":connection_diagnostics.get(login) if login else None,
                    "telemetry":live_account_telemetry.get(login) if login else None,
                    "metaapi_token_configured":bool(METAAPI_TOKEN)}), 200

@app.route("/control",methods=["GET","POST","OPTIONS"])
@app.route("/start",methods=["GET","POST","OPTIONS"])
@app.route("/api/control",methods=["GET","POST","OPTIONS"])
@app.route("/api/start",methods=["GET","POST","OPTIONS"])
def control():
    if request.method=="OPTIONS": return jsonify({"status":"ok"})
    
    data = request.get_json(silent=True) or request.form.to_dict() or request.args.to_dict() or {}
    command=str(data.get("command") or data.get("action") or "START").strip().upper()
    key=str(data.get("license_key") or data.get("key") or "").strip().upper()
    
    if key not in ALLOWED_LICENSES:
        return jsonify({"status":"error","success":False,"message":"Invalid license key."}),200

    # UNCONDITIONAL STOP: Process stop without password checks
    if command=="STOP":
        login=str(data.get("mt5_login") or data.get("login") or "").strip()
        if not login:
            saved=db_get_credentials(key)
            login=saved["mt5_login"] if saved else ""
        if not login: return jsonify({"status":"error","success":False,"message":"MT5 login required to stop."}),200
        active_trading_nodes[login]=False
        telemetry(login,running=False,connection_state="STOP_REQUESTED")
        return jsonify({"status":"success","success":True,"message":"STOP accepted. Worker is stopping."}),200

    login=str(data.get("mt5_login") or data.get("login") or data.get("account") or "").strip()
    password=str(data.get("mt5_password") or data.get("password") or data.get("pass") or "")
    server=str(data.get("mt5_server") or data.get("server") or data.get("broker") or "").strip()
    symbol=str(data.get("mt5_symbol") or data.get("symbol") or "XAUUSD").strip()
    saved=db_get_credentials(key)
    if saved:
        login=login or saved["mt5_login"]
        password=password or saved["mt5_password"]
        server=server or saved["mt5_server"]
        symbol=symbol or saved["mt5_symbol"]

    if command=="SAVE":
        if not login or not server:
            return jsonify({"status":"error","success":False,"message":"MT5 login and server are required to save."}),200
        db_save_credentials(key,login,password,server,symbol)
        return jsonify({"status":"success","success":True,"message":"Credentials saved."}),200

    if command not in {"START","RUN"}:
        return jsonify({"status":"error","success":False,"message":"Unknown command."}),200
    if not login or not password or not server:
        return jsonify({"status":"error","success":False,"message":"Enter MT5 login, password and exact server."}),200
    if not METAAPI_TOKEN:
        return jsonify({"status":"error","success":False,"message":"METAAPI_TOKEN is missing from Render environment variables."}),200

    with state_lock:
        old=trading_threads.get(login)
        if old and old.is_alive():
            if active_trading_nodes.get(login,False):
                return jsonify({"status":"success","success":True,"message":"Worker already running for this login."}),200
            return jsonify({"status":"error","success":False,"message":"Previous worker is still stopping. Wait a few seconds and retry."}),200
        db_save_credentials(key,login,password,server,symbol)
        active_trading_nodes[login]=True
        telemetry(login,running=True,connected_to_broker=False,connection_state="START_REQUESTED",error=None,error_category=None)
        worker=threading.Thread(target=launch_worker,args=(login,password,server,symbol,key),
                                daemon=True,name=f"GoldWorker-{login}")
        trading_threads[login]=worker
        worker.start()
    return jsonify({"status":"success","success":True,
                    "message":"START accepted. Connecting to MetaApi and waiting for MT5 synchronization.",
                    "login":login,"symbol":symbol,"connection_state":"CONNECTING"}),200

if __name__=="__main__":
    port=int(os.environ.get("PORT","10000"))
    print(f"[STARTUP] Gold Mobile EA listening on 0.0.0.0:{port}")
    print(f"[STARTUP] METAAPI_TOKEN configured: {bool(METAAPI_TOKEN)}")
    serve(app,host="0.0.0.0",port=port,threads=8)
