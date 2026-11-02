import os
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
CORS(app)

# ============================================================
# MASTER LICENSE & SECURITY INTEGRITY
# ============================================================
METAAPI_TOKEN = os.environ.get("METAAPI_TOKEN")
PERMANENT_LICENSE_KEY = "BOSSMODE99"

# ============================================================
# SYSTEM STATE STORAGE PIPELINES
# ============================================================
metaapi_instance = None
metaapi_lock = threading.Lock()
active_trading_nodes = {}
trading_threads = {}

# ============================================================
# VIDEO-MATCHED SCALPING PARAMETERS
# ============================================================
BURST_ORDER_COUNT = 8          # Clustered order waves (6-10 positions)
MIN_TARGET_PROFIT_USD = 1.50   # Minimum base profit dollar threshold
PROFIT_EQUITY_RATIO = 0.08     # Target profit per scalp wave (~8-12% equity target)
MAX_ALLOWED_SPREAD_PIPS = 8.0  # Gold spread threshold (0.80 USD on Gold)
POLL_LATENCY_DELAY = 0.02      # Ultra-fast polling interval (20ms)

def get_metaapi_client():
    """Provides thread-safe initialization of the backend controller engine."""
    global metaapi_instance
    if not METAAPI_TOKEN:
        raise RuntimeError("CRITICAL SERVER FAULT: METAAPI_TOKEN environment configuration is missing.")
    with metaapi_lock:
        if metaapi_instance is None:
            metaapi_instance = MetaApi(METAAPI_TOKEN)
    return metaapi_instance

def calculate_video_lot_size(equity: float) -> float:
    """
    Replicates the exact tiered lot escalation observed on XAUUSD:
    - Equity < $50: 0.05
    - Equity $50 - $1,000: 0.10 (Standard base stack from video start)
    - Equity $1,000 - $3,500: 0.30 - 0.50
    - Equity $3,500 - $15,000: 1.00 (Exact video transition tier)
    - Equity $15,000 - $35,000: 1.50
    - Equity $35,000+: 2.00 - 3.00+
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
# FAST MOMENTUM TRACKER
# ============================================================
class MicroTickTracker:
    """Tracks sub-second directional pressure on Gold."""
    def __init__(self, max_ticks=20):
        self.ticks = deque(maxlen=max_ticks)

    def record_tick(self, price: float):
        self.ticks.append(price)

    def determine_bias(self) -> str:
        if len(self.ticks) < 3:
            return "SELL"  # Default bias
        
        # Calculate recent velocity
        delta_short = self.ticks[-1] - self.ticks[-3]
        delta_total = self.ticks[-1] - self.ticks[0]
        
        if delta_short > 0 or delta_total > 0:
            return "BUY"
        else:
            return "SELL"

# ============================================================
# PARALLEL EXECUTION & PURGE ENGINES
# ============================================================
async def fire_stacked_directional_burst(connection, symbol: str, direction: str, volume: float, count: int, login: str):
    """
    Deploys a dense multi-order burst simultaneously in one direction,
    matching the exact cluster layout shown on the MT5 terminal screen.
    """
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
    """
    Simultaneously liquidates all open positions across the terminal.
    """
    close_tasks = [
        connection.close_position(pos["id"])
        for pos in positions
        if "id" in pos
    ]
    if close_tasks:
        results = await asyncio.gather(*close_tasks, return_exceptions=True)
        print(f"[LIQUIDATOR] Complete basket purge finalized. Closed {len(results)} positions in parallel.")

# ============================================================
# CONTINUOUS HIGH-FREQUENCY EXECUTION CORE
# ============================================================
async def high_frequency_trading_engine(login, password, server, symbol):
    """
    Continuous trading engine:
    - Zero resting state (immediately enters upon launch and reloads upon basket close)
    - Automatically compounds lot sizes and dynamic take profits
    - Operates continuously until STOP is received
    """
    print(f"[SYSTEM INITIATED] Connecting active matrix for account {login} on {server} targeting {symbol}")
    account = None
    tick_tracker = MicroTickTracker()

    try:
        api = get_metaapi_client()

        account = await api.metatrader_account_api.create_account({
            "name": f"VideoBot_Node_{login}",
            "type": "cloud",
            "login": str(login),
            "password": password,
            "server": server,
            "platform": "mt5",
            "magic": 9924102,
        })

        await account.wait_connected()
        connection = account.get_streaming_connection()
        await connection.connect()
        await connection.wait_synchronized()
        print(f"[CORE LIVE] Zero-Downtime trading active for: {login}")

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

            # Track tick flow
            mid_price = (current_ask + current_bid) / 2.0
            tick_tracker.record_tick(mid_price)

            # Spread gatekeeper
            current_spread_pips = round((current_ask - current_bid) / 0.1, 2)
            if current_spread_pips > MAX_ALLOWED_SPREAD_PIPS:
                await asyncio.sleep(POLL_LATENCY_DELAY)
                continue

            positions = terminal_state.positions or []
            symbol_positions = [p for p in positions if p.get("symbol") == symbol]
            net_floating_profit = equity - balance

            # Target calculation (scales as balance grows from $18 up to $50k+)
            dynamic_profit_target = max(MIN_TARGET_PROFIT_USD, balance * PROFIT_EQUITY_RATIO)

            # ========================================================
            # 1. BASKET TAKE-PROFIT PURGE TRIGGER
            # ========================================================
            if symbol_positions and net_floating_profit >= dynamic_profit_target:
                print(f"[TARGET HIT] Purging: +${net_floating_profit:.2f} >= Target: ${dynamic_profit_target:.2f}")
                await purge_entire_basket_instantly(connection, symbol_positions)
                await asyncio.sleep(0.01)
                continue

            # ========================================================
            # 2. ZERO-DOWNTIME INSTANT RELOAD (ALWAYS ACTIVE)
            # ========================================================
            if len(symbol_positions) == 0:
                direction = tick_tracker.determine_bias()
                assigned_lot = calculate_video_lot_size(equity if equity > 0 else balance)
                
                print(f"[INSTANT RELOAD] Firing {direction} cluster on {symbol} (Balance: ${balance:.2f}, Lots: {assigned_lot})")
                await fire_stacked_directional_burst(
                    connection, symbol, direction, assigned_lot, BURST_ORDER_COUNT, login
                )
                await asyncio.sleep(0.05)
                continue

            await asyncio.sleep(POLL_LATENCY_DELAY)

    except Exception as e:
        print(f"[CRITICAL ENGINE ERROR] Node failure for {login}: {e}")
        traceback.print_exc()
    finally:
        if account is not None:
            try:
                await account.remove()
                print(f"[CLEANUP] Account node disconnected for {login}")
            except Exception as cleanup_err:
                print(f"[CLEANUP ERROR] Failed to clean node {login}: {cleanup_err}")
        active_trading_nodes.pop(str(login), None)
        trading_threads.pop(str(login), None)
        print(f"[ENGINE STOPPED] Trading node terminated for: {login}")

# ============================================================
# THREAD DISPATCH GATEWAY WRAPPER
# ============================================================
def launch_async_worker_thread(login, password, server, symbol):
    """Spawns an isolated asyncio loop per MT5 account."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(high_frequency_trading_engine(login, password, server, symbol))
    except Exception as thread_err:
        print(f"[THREAD ERROR] Account {login} thread terminated: {thread_err}")
        traceback.print_exc()
    finally:
        try:
            loop.close()
        except Exception:
            pass

# ============================================================
# API ENDPOINTS & CONTROL CONSOLE ROUTING
# ============================================================
@app.route("/", methods=["GET"])
def health_check():
    active_count = len([node for node, running in active_trading_nodes.items() if running])
    return jsonify({
        "status": "online",
        "service": "Hyper-Aggressive Scalper Engine",
        "active_nodes": active_count
    }), 200

@app.route("/status", methods=["GET"])
def status_endpoint():
    active_accounts = [login for login, running in active_trading_nodes.items() if running]
    return jsonify({
        "status": "online",
        "active_accounts": active_accounts
    }), 200

@app.route("/control", methods=["POST"])
def control_endpoint():
    """Universal control endpoint supporting JSON and form data."""
    try:
        data = {}
        if request.is_json:
            data = request.get_json(silent=True) or {}
        if not data:
            data = request.form.to_dict() or request.values.to_dict() or {}

        command = str(data.get("command", "START")).strip().upper()
        
        license_key = str(
            data.get("license_key") or data.get("license") or data.get("key") or ""
        ).strip()

        mt5_login = str(
            data.get("mt5_login") or data.get("login") or data.get("account") or ""
        ).strip()

        mt5_password = str(
            data.get("mt5_password") or data.get("password") or data.get("pass") or ""
        ).strip()

        mt5_server = str(
            data.get("mt5_server") or data.get("server") or ""
        ).strip()

        mt5_symbol = str(
            data.get("mt5_symbol") or data.get("symbol") or "XAUUSDm"
        ).strip()

        # License verification
        if license_key.upper() != PERMANENT_LICENSE_KEY:
            return jsonify({
                "status": "error",
                "message": "License Error: Invalid key. Use BOSSMODE99 for lifetime access."
            }), 400

        if not mt5_login or not mt5_password or not mt5_server:
            return jsonify({"status": "error", "message": "Missing required MT5 credentials."}), 400

        login_str = str(mt5_login).strip()

        if command == "STOP":
            active_trading_nodes[login_str] = False
            return jsonify({
                "status": "success",
                "message": "STOP command accepted. Active engine will disconnect.",
                "login": login_str
            }), 200

        if command == "START":
            if active_trading_nodes.get(login_str, False):
                return jsonify({
                    "status": "success",
                    "message": "Bot is already running for this account.",
                    "login": login_str
                }), 200

            active_trading_nodes[login_str] = True

            worker = threading.Thread(
                target=launch_async_worker_thread,
                args=(login_str, mt5_password, mt5_server, mt5_symbol),
                daemon=True,
                name=f"ScalperWorker-{login_str}"
            )
            trading_threads[login_str] = worker
            worker.start()

            return jsonify({
                "status": "success",
                "message": "START command accepted. Immediate continuous burst trading initiated.",
                "login": login_str,
                "symbol": mt5_symbol
            }), 200

        return jsonify({"status": "error", "message": "Unknown command."}), 400

    except Exception as err:
        print(f"[CONTROL FAULT] {err}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Server Control Fault: {str(err)}"}), 500

# ============================================================
# PRODUCTION SERVER ENTRYPOINT (WAITRESS WSGI)
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    print(f"[PRODUCTION SERVER] Launching Waitress WSGI server on 0.0.0.0:{port}...")
    serve(app, host="0.0.0.0", port=port, threads=8)
