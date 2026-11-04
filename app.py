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
RECONNECT_DELAY_SECONDS = 5

# STRICT 2-ATTEMPT LIMIT: Stops immediately if it cannot connect after 2 tries
MAX_CONSECUTIVE_TRANSIENT_ERRORS = 2

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
        return jsonify({"status": "error", "success": False, "message": error.description, "code": error.code}), error.code
    traceback.print_exc()
    return jsonify({"status": "error", "success": False, "message": "Internal server error. Check Render logs."}), 200

def init_db():
    try:
        with sqlite3.connect(DB_PATH, timeout=15) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS credentials (
                license_key TEXT PRIMARY KEY, mt5_login TEXT NOT NULL,
                mt5_password TEXT NOT NULL, mt5_server TEXT NOT NULL,
                mt5_symbol TEXT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            conn.commit()
    except Exception as e:
        print(f"[DB INIT ERROR] {e}")

def db_save_credentials(key, login, password, server, symbol):
    init_db()
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
    init_db()
    with sqlite3.connect(DB_PATH, timeout=15) as conn:
        row = conn.execute("SELECT mt5_login,mt5_password,mt5_server,mt5_symbol FROM credentials WHERE license_key=?",
                           (key.upper(),)).fetchone()
    if not row: return None
    return {"mt5_login": row[0], "mt5_password": row[1], "mt5_server": row[2], "mt5_symbol": row[3]}

init_db()

FATAL_KEYWORDS = (
    "insufficient funds", "balance is empty", "workloads stopped", "workload stopped",
    "billing", "payment required", "suspended", "unauthorized", "invalid token",
    "authentication failed", "access denied", "invalid credentials", "not enough balance",
    "quota exceeded", "deploy_failed"
)

def safe_error(error):
    msg = str(error)
    if METAAPI_TOKEN: msg = msg.replace(METAAPI_TOKEN, "[REDACTED_TOKEN]")
    msg = re.sub(r"(?i)(password|token|authorization)(\s*[:=]\s*)([^,\s;]+)", r"\1\2[REDACTED]", msg)
    return msg[:1500]

def diagnose_error(error):
    msg = safe_error(error)
    low = msg.lower()
    if any(x in low for x in FATAL_KEYWORDS) or "402" in low:
        return {
            "category": "METAAPI_SUSPENDED_OR_EMPTY",
            "message": "MetaApi workloads stopped or account empty. Log in to app.metaapi.cloud to check your balance or trial status.",
            "should_stop": True
        }
    if "password" in low or "login" in low or "authorization" in low:
        return {
            "category": "MT5_AUTH_FAILED",
            "message": "MT5 Authentication Failed. Verify your MT5 login, trading password, and exact broker server.",
            "should_stop": True
        }
    if "symbol" in low or "market data" in low:
        return {
            "category": "SYMBOL_UNAVAILABLE",
            "message": "Gold symbol quote unavailable. Verify broker suffix (e.g. XAUUSDm, XAUUSD) and trading hours.",
            "should_stop": True
        }
    if "timeout" in low or "timed out" in low:
        return {
            "category": "TIMEOUT",
            "message": "Connection timed out while reaching Exness.",
            "should_stop": False
        }
    return {
        "category": "CONNECTION_FAILED",
        "message": msg,
        "should_stop": False
    }

def record_error(login, error, stage):
    d = diagnose_error(error)
    d.update({"stage": stage, "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()})
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
            await asyncio.sleep(0.3)
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
    accepted = sum(1 for r in results if not isinstance(r, Exception))
    print(f"[ORDER BURST] {login} {direction}: accepted {accepted}/{count}")
    return accepted

async def close_basket(connection, positions):
    tasks = [connection.close_position(p["id"]) for p in positions if p.get("id")]
    await asyncio.gather(*tasks, return_exceptions=True)

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
        return "BUY" if self.ticks[-1] >= self.candle_open else "SELL"

async def high_frequency_trading_engine(login, password, server, symbol, key):
    login = str(login)
    tracker = InstantCandleTracker()
    failures = 0
    telemetry(login, running=True, connected_to_broker=False, connection_state="CONNECTING", error=None)

    while active_trading_nodes.get(login, False):
        connection = None
        try:
            telemetry(login, connection_state="CONNECTING", connected_to_broker=False)
            api = get_metaapi_client()
            account = await get_or_create_account(api, login, password, server)

            acc_state = getattr(account, "state", None)
            if acc_state == "DEPLOY_FAILED":
                raise RuntimeError("MetaApi account status: DEPLOY_FAILED. Check broker login, password, and server.")

            if acc_state != "DEPLOYED":
                telemetry(login, connection_state="DEPLOYING")
                await account.deploy()

            telemetry(login, connection_state="WAITING_FOR_MT5")
            await account.wait_connected()

            connection = account.get_streaming_connection()
            active_connections[login] = connection
            await connection.connect()
            await connection.wait_synchronized()

            active_symbol = await resolve_symbol(connection, symbol)
            failures = 0
            connection_diagnostics.pop(login, None)
            telemetry(login, running=True, connected_to_broker=True, connection_state="CONNECTED",
                      active_symbol=active_symbol, error=None, error_category=None)
            print(f"[CONNECTED] {login} active on {active_symbol}")

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
                    await asyncio.sleep(0.5)
                    continue

                ask, bid = float(price["ask"]), float(price["bid"])
                tracker.record_tick((ask + bid) / 2)
                basket = [p for p in positions if p.get("symbol") == active_symbol]
                pnl = equity - balance

                telemetry(login, running=True, connected_to_broker=True, connection_state="CONNECTED",
                          balance=balance, equity=equity, free_margin=free_margin, margin_level=margin_level,
                          floating_pnl=round(pnl, 2), open_positions_count=len(basket), active_symbol=active_symbol,
                          symbol_price={"ask": ask, "bid": bid}, error=None)

                # Drawdown limit check
                if basket and pnl < -(balance * MAX_ACCOUNT_DRAWDOWN_RATIO):
                    print(f"[RISK] Drawdown limit hit for {login}. Purging basket.")
                    await close_basket(connection, basket)
                    active_trading_nodes[login] = False
                    telemetry(login, running=False, connection_state="STOPPED_DRAWDOWN")
                    break

                # Take-profit check
                target = max(MIN_TARGET_PROFIT_USD, balance * PROFIT_EQUITY_RATIO)
                if basket and pnl >= target:
                    print(f"[PROFIT] Target reached: +${pnl:.2f}. Liquidating basket.")
                    await close_basket(connection, basket)
                    await asyncio.sleep(0.25)
                    continue

                # Reload wave
                if not basket:
                    spread = round((ask - bid) / 0.1, 2)
                    if spread > MAX_ALLOWED_SPREAD_PIPS:
                        await asyncio.sleep(POLL_LATENCY_DELAY)
                        continue
                    direction = tracker.determine_bias()
                    lot = calculate_dynamic_lot_size(equity if equity > 0 else balance, free_margin)
                    count = BURST_ORDER_COUNT if free_margin >= 25 else 2
                    await fire_burst(connection, active_symbol, direction, lot, count, login, key)
                    await asyncio.sleep(0.25)
                    continue

                await asyncio.sleep(POLL_LATENCY_DELAY)

        except asyncio.CancelledError:
            raise
        except Exception as error:
            failures += 1
            d = record_error(login, error, "TRADING_ENGINE")
            
            # Immediately stop on fatal errors OR after 2 failed attempts
            if d["should_stop"] or failures >= MAX_CONSECUTIVE_TRANSIENT_ERRORS:
                active_trading_nodes[login] = False
                telemetry(login, running=False, connected_to_broker=False,
                          connection_state="STOPPED_ERROR", error=d["message"], error_category=d["category"])
                print(f"[STOPPED PERMANENTLY] {login}: {d['message']} (Failed {failures} times)")
                break
            else:
                telemetry(login, running=True, connected_to_broker=False,
                          connection_state="RETRYING", error=f"Attempt {failures}/2 failed: {d['message']}", error_category=d["category"])
                print(f"[RETRYING {failures}/2] Waiting before attempt 2...")

        finally:
            if connection is not None:
                try: await connection.close()
                except Exception: pass
            active_connections.pop(login, None)

        if active_trading_nodes.get(login, False):
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)

    active_trading_nodes[login] = False
    prev = live_account_telemetry.get(login, {})
    prev.update({"running": False, "connected_to_broker": False})
    live_account_telemetry[login] = prev
    trading_threads.pop(login, None)
    active_connections.pop(login, None)
    print(f"[ENGINE STOPPED] Worker terminated for {login}")

def launch_worker(login, password, server, symbol, key):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(high_frequency_trading_engine(login, password, server, symbol, key))
    except Exception as e:
        d = record_error(login, e, "WORKER_THREAD")
        telemetry(login, running=False, connected_to_broker=False, connection_state="WORKER_CRASHED", error=d["message"])
        active_trading_nodes[login] = False
    finally:
        try: loop.close()
        except Exception: pass
        if trading_threads.get(login) is threading.current_thread():
            trading_threads.pop(login, None)

# ============================================================
# EMBEDDED WEB DASHBOARD
# ============================================================
STANDALONE_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>Gold Scalper AI - Matrix Control</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background-color: #0b0e14; color: #f3f4f6; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 16px; }
    .card { width: 100%; max-width: 440px; background: rgba(22, 27, 34, 0.95); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 24px; padding: 24px; box-shadow: 0 20px 50px rgba(0,0,0,0.6); }
    .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1f2937; padding-bottom: 16px; margin-bottom: 20px; }
    .logo { width: 42px; height: 42px; border-radius: 14px; background: linear-gradient(135deg, #10b981, #6ee7b7); color: #000; font-weight: 900; font-size: 22px; display: flex; align-items: center; justify-content: center; }
    .title h1 { font-size: 18px; font-weight: 800; color: #fff; }
    .title p { font-size: 12px; color: #34d399; }
    .badge { font-size: 11px; padding: 4px 10px; border-radius: 999px; border: 1px solid #374151; background: #111827; color: #9ca3af; font-family: monospace; font-weight: bold; }
    .badge.online { background: #064e3b; color: #34d399; border-color: #059669; }
    .badge.failed { background: #4c0519; color: #f43f5e; border-color: #e11d48; }
    .telemetry { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; background: #111827; border: 1px solid #1f2937; border-radius: 16px; padding: 14px; margin-bottom: 18px; font-family: monospace; font-size: 12px; }
    .form-group { margin-bottom: 14px; }
    label { display: block; font-size: 11px; font-weight: 700; color: #9ca3af; text-transform: uppercase; margin-bottom: 6px; }
    input { width: 100%; background: #0f172a; border: 1px solid #334155; border-radius: 12px; padding: 10px 14px; color: #f8fafc; font-size: 14px; font-family: monospace; outline: none; }
    input:focus { border-color: #10b981; }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .status-box { background: rgba(0,0,0,0.4); border: 1px solid #1f2937; border-radius: 12px; padding: 12px; font-size: 12px; color: #9ca3af; font-family: monospace; min-height: 48px; display: flex; align-items: center; margin-bottom: 18px; line-height: 1.4; }
    .btn-group { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px; }
    button { padding: 14px; border-radius: 14px; font-weight: 800; font-size: 13px; cursor: pointer; border: none; }
    .btn-launch { background: linear-gradient(135deg, #10b981, #059669); color: #000; }
    .btn-stop { background: linear-gradient(135deg, #e11d48, #be123c); color: #fff; }
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <div style="display:flex; align-items:center; gap:12px;">
        <div class="logo">⚡</div>
        <div class="title">
          <h1>Gold Scalper AI</h1>
          <p>● Multi-Wave Execution</p>
        </div>
      </div>
      <div id="badgeStatus" class="badge">OFFLINE</div>
    </div>

    <div class="telemetry">
      <div><span style="color:#64748b;">Balance:</span> <strong id="lblBalance" style="color:#fff;">$0.00</strong></div>
      <div><span style="color:#64748b;">Equity:</span> <strong id="lblEquity" style="color:#34d399;">$0.00</strong></div>
    </div>

    <div class="form-group">
      <label>Master License Key</label>
      <input type="text" id="txtKey" value="BOSSMODE99" style="text-transform:uppercase; color:#34d399;" />
    </div>

    <div class="form-group">
      <label>MT5 Account Login</label>
      <input type="text" id="txtLogin" placeholder="21648212" />
    </div>

    <div class="form-group">
      <label>MT5 Trading Password</label>
      <input type="password" id="txtPass" placeholder="••••••••" />
    </div>

    <div class="grid-2 form-group">
      <div>
        <label>Server</label>
        <input type="text" id="txtServer" placeholder="Exness-MT5Trial" />
      </div>
      <div>
        <label>Symbol</label>
        <input type="text" id="txtSymbol" value="XAUUSD" />
      </div>
    </div>

    <div id="msgBox" class="status-box">Ready. Configure credentials and click Launch Bot.</div>

    <div class="btn-group">
      <button class="btn-launch" onclick="handleStart()">⚡ LAUNCH BOT</button>
      <button class="btn-stop" onclick="handleStop()">🛑 STOP BOT</button>
    </div>
  </div>

  <script>
    async function loadConfig() {
      const key = (document.getElementById('txtKey').value || 'BOSSMODE99').trim().toUpperCase();
      try {
        const res = await fetch('/api/account?license_key=' + key);
        const data = await res.json();
        if (data && data.login) {
          document.getElementById('txtLogin').value = data.login;
          document.getElementById('txtServer').value = data.server || 'Exness-MT5Trial';
          document.getElementById('txtSymbol').value = data.symbol || 'XAUUSD';
        }
      } catch (e) {}
    }

    async function pollStatus() {
      try {
        const res = await fetch('/status');
        const data = await res.json();
        const badge = document.getElementById('badgeStatus');
        const msg = document.getElementById('msgBox');

        if (data.connected_to_broker) {
          badge.className = 'badge online';
          badge.innerText = 'CONNECTED';
        } else if (data.status_text === 'FAILED' || data.status_text === 'STOPPED_ERROR') {
          badge.className = 'badge failed';
          badge.innerText = 'FAILED';
        } else {
          badge.className = 'badge';
          badge.innerText = data.running ? 'CONNECTING' : 'OFFLINE';
        }

        document.getElementById('lblBalance').innerText = '$' + (Number(data.balance) || 0).toFixed(2);
        document.getElementById('lblEquity').innerText = '$' + (Number(data.equity) || 0).toFixed(2);

        // Display diagnostic error message and halt if stopped after 2 attempts
        if (data.last_error && !data.running) {
          msg.innerHTML = '<span style="color:#f87171;">❌ ' + data.last_error + '</span>';
        }
      } catch (e) {}
    }

    async function handleStart() {
      const key = document.getElementById('txtKey').value.trim().toUpperCase();
      const login = document.getElementById('txtLogin').value.trim();
      const pass = document.getElementById('txtPass').value.trim();
      const server = document.getElementById('txtServer').value.trim();
      const symbol = document.getElementById('txtSymbol').value.trim();
      const msg = document.getElementById('msgBox');

      if (key !== 'BOSSMODE98' && key !== 'BOSSMODE99') {
        msg.innerHTML = '<span style="color:#f87171;">❌ Invalid License Key!</span>';
        return;
      }
      msg.innerHTML = '<span style="color:#34d399;">⚡ Connecting to Exness terminal (Max 2 attempts)...</span>';

      try {
        const res = await fetch('/api/control', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: 'START', license_key: key, mt5_login: login, mt5_password: pass, mt5_server: server, mt5_symbol: symbol })
        });
        const data = await res.json();
        if (data.status === 'success') {
          msg.innerHTML = '<span style="color:#34d399;">✅ ' + (data.message || 'Connecting...') + '</span>';
        } else {
          msg.innerHTML = '<span style="color:#f87171;">❌ ' + (data.message || 'Start failed.') + '</span>';
        }
        pollStatus();
      } catch (e) {
        msg.innerHTML = '<span style="color:#f87171;">❌ Network error contacting backend.</span>';
      }
    }

    async function handleStop() {
      const key = document.getElementById('txtKey').value.trim().toUpperCase();
      const login = document.getElementById('txtLogin').value.trim();
      const msg = document.getElementById('msgBox');
      msg.innerHTML = '<span style="color:#fbbf24;">🛑 Stopping bot and clearing session...</span>';

      try {
        await fetch('/api/control', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: 'STOP', license_key: key, mt5_login: login })
        });
        msg.innerHTML = '<span style="color:#9ca3af;">🛑 Scalper terminated.</span>';
        pollStatus();
      } catch (e) {
        msg.innerHTML = '<span style="color:#f87171;">❌ Stop command failed.</span>';
      }
    }

    document.getElementById('txtKey').addEventListener('change', loadConfig);
    loadConfig();
    pollStatus();
    setInterval(pollStatus, 3000);
  </script>
</body>
</html>
"""

# ============================================================
# API ENDPOINTS
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
    return render_template_string(STANDALONE_HTML_TEMPLATE)

@app.route("/api/account", methods=["GET", "OPTIONS"])
@app.route("/get_credentials", methods=["GET", "OPTIONS"])
def account_metadata():
    if request.method == "OPTIONS": return jsonify({"status": "ok"})
    key = request.args.get("license_key", "BOSSMODE99").strip().upper()
    if key not in ALLOWED_LICENSES: return jsonify({"status": "error", "message": "Invalid license key."}), 200
    saved = db_get_credentials(key)
    if not saved: return jsonify({"status": "success", "login": "21648212", "server": "Exness-MT5Trial", "symbol": "XAUUSD"})
    return jsonify({"status": "success", "login": saved["mt5_login"], "server": saved["mt5_server"], "symbol": saved["mt5_symbol"]})

@app.route("/status", methods=["GET", "OPTIONS"])
@app.route("/api/status", methods=["GET", "OPTIONS"])
def status_endpoint():
    try:
        active_accounts = [login for login, running in active_trading_nodes.items() if running]
        is_running = len(active_accounts) > 0
        is_connected = False
        status_text = "OFFLINE"
        balance = 0.0
        equity = 0.0
        last_error = None

        first_login = active_accounts[0] if is_running else (list(live_account_telemetry.keys())[0] if live_account_telemetry else None)
        if first_login and first_login in live_account_telemetry:
            t = live_account_telemetry[first_login]
            is_connected = t.get("connected_to_broker", False)
            status_text = t.get("connection_state", "CONNECTED" if is_connected else "CONNECTING")
            balance = t.get("balance", 0.0)
            equity = t.get("equity", 0.0)
            last_error = t.get("error")

        return jsonify({
            "status": "online",
            "running": is_running,
            "connected_to_broker": is_connected,
            "status_text": status_text,
            "balance": balance,
            "equity": equity,
            "last_error": last_error,
            "active_nodes_count": len(active_accounts),
            "telemetry": live_account_telemetry
        }), 200
    except Exception as e:
        return jsonify({
            "status": "online",
            "running": False,
            "connected_to_broker": False,
            "status_text": "ERROR",
            "last_error": str(e)
        }), 200

@app.route("/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/start", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/start", methods=["GET", "POST", "OPTIONS"])
def control_dispatcher():
    if request.method == "OPTIONS": return jsonify({"status": "ok"})
    data = extract_request_data(request)
    command = str(data.get("command") or data.get("action") or "START").strip().upper()
    key = str(data.get("license_key") or data.get("key") or "").strip().upper()

    if key not in ALLOWED_LICENSES:
        return jsonify({"status": "error", "success": False, "message": "Invalid license key."}), 200

    if command == "STOP":
        login = str(data.get("mt5_login") or data.get("login") or "").strip()
        if not login:
            saved = db_get_credentials(key)
            login = saved["mt5_login"] if saved else ""
        if not login:
            for l in list(active_trading_nodes.keys()):
                active_trading_nodes[l] = False
            return jsonify({"status": "success", "message": "All trading engines stopped."}), 200

        active_trading_nodes[login] = False
        telemetry(login, running=False, connection_state="STOPPED")
        return jsonify({"status": "success", "message": f"STOP accepted for account {login}."}), 200

    login = str(data.get("mt5_login") or data.get("login") or "").strip()
    password = str(data.get("mt5_password") or data.get("password") or "")
    server = str(data.get("mt5_server") or data.get("server") or "").strip()
    symbol = str(data.get("mt5_symbol") or data.get("symbol") or "XAUUSD").strip()

    saved = db_get_credentials(key)
    if saved:
        login = login or saved["mt5_login"]
        password = password or saved["mt5_password"]
        server = server or saved["mt5_server"]
        symbol = symbol or saved["mt5_symbol"]

    if not login or not password or not server:
        return jsonify({"status": "error", "message": "Missing credentials. Enter login, password, and server."}), 200

    with state_lock:
        old = trading_threads.get(login)
        if old and old.is_alive():
            if active_trading_nodes.get(login, False):
                return jsonify({"status": "success", "message": "Worker already running for this login."}), 200
            return jsonify({"status": "error", "message": "Previous session stopping. Wait 5s and retry."}), 200

        db_save_credentials(key, login, password, server, symbol)
        active_trading_nodes[login] = True
        telemetry(login, running=True, connected_to_broker=False, connection_state="CONNECTING", error=None)

        worker = threading.Thread(target=launch_worker, args=(login, password, server, symbol, key),
                                daemon=True, name=f"GoldWorker-{login}")
        trading_threads[login] = worker
        worker.start()

    return jsonify({
        "status": "success",
        "message": "START accepted. Attempting to connect (maximum 2 retries)...",
        "login": login,
        "symbol": symbol
    }), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    print(f"[STARTUP] Gold Scalper active on port {port}")
    serve(app, host="0.0.0.0", port=port, threads=8)
