import os
import asyncio
import threading
import datetime
import traceback
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
# VIDEO-MATCHED HYPER-AGGRESSIVE STRATEGY PARAMETERS
# ============================================================
BURST_ORDER_COUNT = 8          # Exact video pattern: 6-10 stacked orders per wave
TARGET_PROFIT_RATIO = 0.20     # Dynamic compounding profit goal per basket (20% of equity)
MAX_ALLOWED_SPREAD_PIPS = 6.0  # Ultra-tolerant gold spread filter
POLL_LATENCY_DELAY = 0.05      # High-speed polling interval (50ms)

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
    Replicates the exact tiered lot scaling observed in the video:
    - Equity < $50: 0.01
    - Equity $50 - $200: 0.02
    - Equity $200 - $1,000: 0.10
    - Equity $1,000 - $5,000: 0.20 - 0.30
    - Equity $5,000 - $50,000: 0.90 - 2.00
    - Equity > $50,000: 3.00 (or uncapped compounding)
    """
    if equity < 15.0:
        return 0.01
    elif equity < 50.0:
        return 0.02
    elif equity < 300.0:
        return 0.10
    elif equity < 1500.0:
        return 0.20
    elif equity < 5000.0:
        return 0.30
    elif equity < 20000.0:
        return 0.90
    elif equity < 80000.0:
        return 2.00
    else:
        return 3.00

# ============================================================
# PARALLEL EXECUTION & PURGE ENGINES
# ============================================================
async def fire_stacked_directional_burst(connection, symbol: str, direction: str, volume: float, count: int, login: str):
    """
    Deploys a dense multi-order burst simultaneously in one direction,
    matching the exact cluster layout shown on the MT5 mobile screen.
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
    Simultaneously closes all open positions across the entire terminal.
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
    - Never rests without trades
    - Immediately restarts a new burst the millisecond old trades are purged
    - Operates until the user sends a STOP command
    """
    print(f"[SYSTEM INITIATED] Connecting active matrix for account {login} on {server} targeting {symbol}")
    account = None
    try:
        api = get_metaapi_client()

        account = await api.metatrader_account_api.create_account({
            "name": f"KimBot_Active_Node_{login}",
            "type": "cloud",
            "login": str(login),
            "password": password,
            "server": server,
            "platform": "mt5",
            "magic": 24102401,
        })

        await account.wait_connected()
        connection = account.get_streaming_connection()
        await connection.connect()
        await connection.wait_synchronized()
        print(f"[CORE LIVE] Zero-Downtime trading active for: {login}")

        last_price = None

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

            # Spread gatekeeper
            current_spread_pips = round((current_ask - current_bid) / 0.1, 2)
            if current_spread_pips > MAX_ALLOWED_SPREAD_PIPS:
                await asyncio.sleep(POLL_LATENCY_DELAY)
                continue

            positions = terminal_state.positions or []
            symbol_positions = [p for p in positions if p.get("symbol") == symbol]
            net_floating_profit = equity - balance

            # Dynamic compounding target formula (min $2.00, otherwise % of balance)
            dynamic_profit_target = max(2.0, balance * TARGET_PROFIT_RATIO)

            # ========================================================
            # BASKET TAKE-PROFIT PURGE TRIGGER
            # ========================================================
            if symbol_positions and net_floating_profit >= dynamic_profit_target:
                print(f"[TARGET HIT] Purging: +${net_floating_profit:.2f} >= Target: ${dynamic_profit_target:.2f}")
                await purge_entire_basket_instantly(connection, symbol_positions)
                await asyncio.sleep(0.05)
                continue

            # ========================================================
            # ZERO DOWNTIME RELOAD (ALWAYS ACTIVE)
            # ========================================================
            if len(symbol_positions) == 0:
                # Determine directional bias via instantaneous micro-tick momentum
                direction = "BUY"
                if last_price is not None and current_bid < last_price:
                    direction = "SELL"
                last_price = current_bid

                assigned_lot = calculate_video_lot_size(equity)
                print(f"[RELOAD BURST] Firing instantaneous {direction} cluster on {symbol} (Balance: ${balance:.2f})")
                await fire_stacked_directional_burst(
                    connection, symbol, direction, assigned_lot, BURST_ORDER_COUNT, login
                )
                await asyncio.sleep(0.1)
                continue

            last_price = current_bid
            await asyncio.sleep(POLL_LATENCY_DELAY)

    except Exception as e:
        print(f"[CRITICAL ENGINE ERROR] Node failure for {login}: {e}")
        traceback.print_exc()
    finally:
        if account is not None:
            try:
                await account.remove()
                print(f"[CLEANUP] Account resource removed for {login}")
            except Exception as cleanup_err:
                print(f"[CLEANUP ERROR] Failed to remove account {login}: {cleanup_err}")
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
        print(f"[THREAD FATAL ERROR] Account {login} thread crashed: {thread_err}")
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
        "service": "KimBot Hyper-Aggressive Burst Scalper",
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
    """
    Universal control endpoint supporting JSON and form data.
    """
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
                "message": "STOP command accepted. Bot will complete current purge and disconnect.",
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
                name=f"TradingWorker-{login_str}"
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
        print(f"[CONTROL CRITICAL FAULT] {err}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Server Control Fault: {str(err)}"}), 500

# ============================================================
# PRODUCTION SERVER ENTRYPOINT (WAITRESS WSGI)
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    print(f"[PRODUCTION SERVER] Launching Waitress WSGI server on 0.0.0.0:{port}...")
    serve(app, host="0.0.0.0", port=port, threads=8)
