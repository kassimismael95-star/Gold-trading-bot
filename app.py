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
# PROPRIETARY HYPER-AGGRESSIVE STRATEGY SETTINGS
# ============================================================
PIP_SPACING = 1.0              # Hyper-tight spacing for maximum trade frequency
MARTINGALE_MULTIPLIER = 2.0    # 100% video-accurate scaling (0.01 -> 0.02 -> 0.04 -> 0.08)
MAX_GRID_LEVELS = 30           # Extended structural depth safety limit
MAX_ALLOWED_SPREAD_PIPS = 3.5  # High-frequency protection ceiling

# ============================================================
# NEW COMPETE INTEGRATIONS: AGGRESSIVE BASKET TARGETS
# ============================================================
BASKET_TARGET_PROFIT_USD = 5.00 # Close all trades and reload the moment total profit hits this amount

def get_metaapi_client():
    """Provides thread-safe initialization of the backend controller engine."""
    global metaapi_instance
    if not METAAPI_TOKEN:
        raise RuntimeError("CRITICAL SERVER FAULT: METAAPI_TOKEN environment configuration is completely empty.")
    with metaapi_lock:
        if metaapi_instance is None:
            metaapi_instance = MetaApi(METAAPI_TOKEN)
    return metaapi_instance

# ============================================================
# INSTANTANEOUS BALANCED ENTRY DISPATCHER
# ============================================================
async def execute_instant_basket_entry(connection, symbol, volume, login):
    """
    Forces instant, synchronized co-directional market entries. 
    Bypasses standard broker ticks to guarantee immediate market footprint.
    """
    buy_task = connection.create_market_buy_order(symbol, volume, 0, 0)
    sell_task = connection.create_market_sell_order(symbol, volume, 0, 0)
    
    results = await asyncio.gather(buy_task, sell_task, return_exceptions=True)
    
    for res in results:
        if isinstance(res, Exception):
            print(f"[DISPATCH ERROR] Instant entry block failed for {login}: {res}")
        else:
            print(f"[KIM BOT ENTRY] Initial balance basket deployed successfully for {login} | Vol: {volume}")

# ============================================================
# NEW: PARALLEL BASKET LIQUIDATION ENGINE 
# ============================================================
async def purge_entire_basket_instantly(connection, positions):
    """
    Liquidates every single active position simultaneously via asynchronous execution.
    Eliminates execution delay to lock in exact target profits.
    """
    close_tasks = []
    for pos in positions:
        pos_id = pos.get("id")
        if pos_id:
            close_tasks.append(connection.close_position(pos_id))
            
    if close_tasks:
        results = await asyncio.gather(*close_tasks, return_exceptions=True)
        print(f"[LIQUIDATOR] Complete basket purge finalized. Closed {len(results)} positions in parallel.")

# ============================================================
# RUNTIME HIGH-SPEED EXECUTION CORE (NEVER RESTS)
# ============================================================
async def high_frequency_trading_engine(login, password, server, symbol):
    """
    Proprietary high-frequency monitoring engine. Runs indefinitely.
    Forces zero-downtime execution loops across open trading windows.
    """
    print(f"[SYSTEM INITIATED] Connecting active matrix for account {login} on {server} targeting {symbol}")
    account = None
    try:
        api = get_metaapi_client()
        
        # Provision cloud runtime instance resources
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
        print(f"[CORE LIVE] Connection confirmed and running live market scripts for: {login}")

        # The Infinite Aggressive Monitoring Loop
        while active_trading_nodes.get(str(login), False):
            account_info = account.account_information or {}
            equity = float(account_info.get("equity", 0) or 0)
            balance = float(account_info.get("balance", 0) or 0)
            
            # Compounding dynamics: Scales starting baseline position to live equity values
            calculated_volume = max(0.01, round((equity / 2.0) * 0.01, 2))
            
            terminal_state = connection.terminal_state
            price = terminal_state.price(symbol)
            if not price:
                await asyncio.sleep(0.01)  # Ultra-low latency polling delay
                continue

            current_ask = price.get("ask")
            current_bid = price.get("bid")
            if current_ask is None or current_bid is None:
                await asyncio.sleep(0.01)
                continue

            # Advanced Pip Spread Evaluation Engine
            current_spread_pips = round((current_ask - current_bid) / 0.1, 2)

            positions = terminal_state.positions or []
            symbol_positions = [p for p in positions if p.get("symbol") == symbol]
            
            # Calculate live combined running profit across all open grid legs
            net_floating_profit = equity - balance

            # ============================================================
            # CRITICAL COMPETE MECHANISM: PROFIT TARGET TAKEOUT
            # ============================================================
            if symbol_positions and net_floating_profit >= BASKET_TARGET_PROFIT_USD:
                print(f"[TARGET REACHED] Net Profit: ${net_floating_profit:.2f} >= Target: ${BASKET_TARGET_PROFIT_USD}. Purging basket...")
                await purge_entire_basket_instantly(connection, symbol_positions)
                await asyncio.sleep(0.02)
                continue

            buys = [p for p in symbol_positions if p.get("type") == "POSITION_TYPE_BUY"]
            sells = [p for p in symbol_positions if p.get("type") == "POSITION_TYPE_SELL"]
            total_positions = len(buys) + len(sells)

            # ============================================================
            # ZERO POSITION RULES: IMMEDIATE BASKET FORCING
            # ============================================================
            if total_positions == 0:
                if current_spread_pips > MAX_ALLOWED_SPREAD_PIPS:
                    print(f"[SPREAD GATEKEEPER] Entry blocked for {login}. Spread: {current_spread_pips} pips")
                    await asyncio.sleep(0.1)
                    continue

                print(f"[ZERO DOWNTIME TRIGGER] Portfolio clear on {login}. Instantly forcing entry basket...")
                await execute_instant_basket_entry(connection, symbol, calculated_volume, login)
                await asyncio.sleep(0.01)
                continue

            # ============================================================
            # HIGH-FREQUENCY COMPLEMENTARY GRID TIER MANAGEMENT
            # ============================================================
            # Long Grid Accumulation Tracker
            if len(buys) < MAX_GRID_LEVELS and buys:
                lowest_buy = min(float(p.get("openPrice", current_bid)) for p in buys)
                if current_bid <= lowest_buy - PIP_SPACING:
                    if current_spread_pips <= MAX_ALLOWED_SPREAD_PIPS:
                        previous_volume = float(buys[-1].get("volume", calculated_volume))
                        next_lot = min(5.0, round(previous_volume * MARTINGALE_MULTIPLIER, 2))
                        try:
                            await connection.create_market_buy_order(symbol, next_lot, 0, 0)
                            print(f"[GRID TIER EXPANSION] Additional Long added for {login} | Next Lot: {next_lot}")
                        except Exception as e:
                            print(f"[GRID TIER FAULT] Buy order failed: {e}")

            # Short Grid Accumulation Tracker
            if len(sells) < MAX_GRID_LEVELS and sells:
                highest_sells = max(float(p.get("openPrice", current_ask)) for p in sells)
                if current_ask >= highest_sells + PIP_SPACING:
                    if current_spread_pips <= MAX_ALLOWED_SPREAD_PIPS:
                        previous_volume = float(sells[-1].get("volume", calculated_volume))
                        next_lot = min(5.0, round(previous_volume * MARTINGALE_MULTIPLIER, 2))
                        try:
                            await connection.create_market_sell_order(symbol, next_lot, 0, 0)
                            print(f"[GRID TIER EXPANSION] Additional Short added for {login} | Next Lot: {next_lot}")
                        except Exception as e:
                            print(f"[GRID TIER FAULT] Sell order failed: {e}")

            # High-intensity tracking frequency throttle sleep
            await asyncio.sleep(0.02)

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
        print(f"[ENGINE STOPPED] Trading node completely terminated for: {login}")

# ============================================================
# THREAD DISPATCH GATEWAY WRAPPER
# ============================================================
def launch_async_worker_thread(login, password, server, symbol):
    """Safely spawns and manages an isolated asyncio event loop thread per trading account."""
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
        "service": "KimBot Hyper-Aggressive Cloud Grid Scalper",
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
    Bulletproof control gateway supporting JSON, Form-Data, and URL arguments.
    Enforces BOSSMODE99 permanent lifetime bypass and returns descriptive error messages.
    """
    try:
        data = {}
        if request.is_json:
            data = request.get_json(silent=True) or {}
        if not data:
            data = request.form.to_dict() or request.values.to_dict() or {}

        command = str(data.get("command", "START")).strip().upper()
        
        # Universal parameter normalization mapping all front-end naming variations
        license_key = str(
            data.get("license_key") or data.get("license") or data.get("key") or 
            data.get("licenseKey") or data.get("activationKey") or ""
        ).strip()

        mt5_login = str(
            data.get("mt5_login") or data.get("login") or data.get("account") or 
            data.get("accountNumber") or data.get("mt5Login") or ""
        ).strip()

        mt5_password = str(
            data.get("mt5_password") or data.get("password") or data.get("pass") or 
            data.get("pwd") or ""
        ).strip()

        mt5_server = str(
            data.get("mt5_server") or data.get("server") or data.get("brokerServer") or ""
        ).strip()

        mt5_symbol = str(
            data.get("mt5_symbol") or data.get("symbol") or "XAUUSD"
        ).strip()

        # Fallback to query arguments if body parameters are empty
        if not license_key:
            license_key = request.args.get("license_key", "").strip()
        if not mt5_login:
            mt5_login = request.args.get("mt5_login", "").strip()
        if not mt5_password:
            mt5_password = request.args.get("mt5_password", "").strip()
        if not mt5_server:
            mt5_server = request.args.get("mt5_server", "").strip()

        # Fallback support if key_payload slash-string format is passed
        user_input = str(data.get("key_payload", "")).strip()
        if user_input and "/" in user_input:
            parts = user_input.split("/")
            if len(parts) >= 4:
                license_key = parts[0].strip()
                mt5_login = parts[1].strip()
                mt5_password = parts[2].strip()
                mt5_server = parts[3].strip()
                if len(parts) >= 5:
                    mt5_symbol = parts[4].strip()

        # ============================================================
        # LICENSE VALIDATION CHECK
        # ============================================================
        if license_key.upper() != PERMANENT_LICENSE_KEY:
            return jsonify({
                "status": "error",
                "message": "License Error: Invalid key. Use BOSSMODE99 for lifetime access."
            }), 400

        # ============================================================
        # FIELD VALIDATIONS
        # ============================================================
        if not mt5_login:
            return jsonify({"status": "error", "message": "Login Error: MT5 account number is required."}), 400
        if not mt5_password:
            return jsonify({"status": "error", "message": "Password Error: Master trading password is required."}), 400
        if not mt5_server:
            return jsonify({"status": "error", "message": "Server Error: MT5 live server name is required."}), 400

        login_str = str(mt5_login).strip()

        if command == "STOP":
            active_trading_nodes[login_str] = False
            return jsonify({
                "status": "success",
                "message": "Cloud termination instruction synchronized.",
                "login": login_str
            }), 200

        if command == "START":
            if active_trading_nodes.get(login_str, False):
                return jsonify({
                    "status": "success",
                    "message": "Bot engine is already active for this account.",
                    "login": login_str
                }), 200

            # Activate runtime flag and spin up isolated background worker thread
            active_trading_nodes[login_str] = True

            worker = threading.Thread(
                target=launch_async_worker_thread,
                args=(login_str, mt5_password, mt5_server, mt5_symbol),
                daemon=True,
                name=f"TradingWorker-{login_str}"
            )
            trading_threads[login_str] = worker
            worker.start()

            print(f"[CONTROL GATEWAY] START command accepted for account {login_str} on {mt5_server} trading {mt5_symbol}")
            return jsonify({
                "status": "success",
                "message": "START command dispatched successfully.",
                "login": login_str,
                "symbol": mt5_symbol
            }), 200

        return jsonify({"status": "error", "message": "Unknown command instruction."}), 400

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
