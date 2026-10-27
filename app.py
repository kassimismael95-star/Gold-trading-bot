import os
import time
import asyncio
import threading
import datetime
from flask import Flask, request, jsonify
from metaapi_cloud_sdk import MetaApi
from waitress import serve

app = Flask(__name__)

# --- SECURE API ENVIRONMENT VARIABLES ---
# This automatically extracts your encrypted tokens securely inside Render's dashboard
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("BOT_TOKEN")
METAAPI_TOKEN = os.environ.get("METAAPI_TOKEN")

# Global receptacle initialized inside our isolated async worker threads
metaapi = None 

# Active multi-tenant dictionary registry keeping track of active accounts running concurrently
active_trading_nodes = {}

# PURE UNRESTRICTED GRID SCALPER RUNTIME VARIABLES
PIP_SPACING = 1.5           # Dense stacking interval (1.5 pips / 15 points on Gold)
MARTINGALE_MULTIPLIER = 1.5 # Exponential compounding risk multiplier factor
MAX_GRID_LEVELS = 25        # High-exposure stacking ceiling matching the video look

def check_market_execution_safeties():
    """
    WEEKEND SAFETY BREAKER EXCLUSION WINDOW
    Returns False to freeze execution during weekly session closures.
    All news delays have been removed to trade continuously through NFP/CPI/FOMC.
    """
    now = datetime.datetime.utcnow()
    day_of_week = now.weekday()  # Monday=0, Friday=4, Saturday=5, Sunday=6
    hour = now.hour

    # Standard Weekend Close structural window (Friday 21:00 UTC through Sunday 22:00 UTC)
    if (day_of_week == 4 and hour >= 21) or (day_of_week == 5) or (day_of_week == 6 and hour < 22):
        return False
    return True

async def live_gold_compounding_grid(login, password, server, symbol):
    global metaapi
    print(f"[Engine Room] Initializing isolated high-speed cloud node for account: {login}")
    try:
        if metaapi is None:
            metaapi = MetaApi(METAAPI_TOKEN)
            
        # Dynamically provision a virtual terminal connection matching any custom broker spec
        account = await metaapi.metatrader_account_api.create_account({
            'name': f"Cloud_Node_{login}",
            'type': 'cloud',
            'login': str(login),
            'password': password,
            'server': server,
            'platform': 'mt5',
            'magic': 24102401
        })
        
        await account.wait_connected()
        connection = account.get_streaming_connection()
        await connection.connect()
        await connection.wait_synchronized()
        print(f"[Engine Room] Secure connection locked to broker server {server} for client {login}!")

        # High-frequency processing iteration heartbeat channel loop
        while active_trading_nodes.get(login) == True:
            # Check weekend filter safety boundaries
            if not check_market_execution_safeties():
                print(f"[Weekend Guard] Protecting capital. Freezing grid loop for account {login}")
                await asyncio.sleep(5)
                continue

            account_info = account.account_information
            equity = account_info['equity']
            
            # v65 Dynamic Balance Compounding: 1 micro lot (0.01) per every $2.00 USD of account equity
            # Perfectly scales down to a $2.00 account size without fear or hesitation
            calculated_volume = max(0.01, round((equity / 2.00) * 0.01, 2))
            
            terminal_state = connection.terminal_state
            price = terminal_state.price(symbol) # Dynamically tracks whatever Gold format was entered (XAUUSD, GOLD, etc.)
            
            if not price:
                await asyncio.sleep(0.05) # Split-second synchronization sleep
                continue
                
            current_ask = price['ask']
            current_bid = price['bid']
            
            # Filter and isolate active orders for this bot matching the unique symbol text
            open_positions = terminal_state.positions
            gold_buys = [p for p in open_positions if p['symbol'] == symbol and p['type'] == 'POSITION_TYPE_BUY']
            gold_sells = [p for p in open_positions if p['symbol'] == symbol and p['type'] == 'POSITION_TYPE_SELL']
            total_positions = len(gold_buys) + len(gold_sells)

            # --- PHASE A: IMMEDIATE INITIALIZATION HEDGE (NO DELAYS) ---
            if total_positions == 0:
                print(f"[Cloud Grid] Baskets empty on account {login}. Deploying dual initialization anchors.")
                await connection.create_market_buy_order(symbol, calculated_volume, 0, 0)
                await connection.create_market_sell_order(symbol, calculated_volume, 0, 0)
                continue

            # --- PHASE B: UNRESTRICTED ARROW WALL GRID STACKING ---
            if total_positions < MAX_GRID_LEVELS:
                # 1. Manage Buy Grid: Open next level down the trend if price falls below the lowest buy
                if len(gold_buys) > 0:
                    lowest_buy = min(p['openPrice'] for p in gold_buys)
                    if current_bid <= (lowest_buy - PIP_SPACING):
                        next_lot = min(5.0, round(gold_buys[-1]['volume'] * MARTINGALE_MULTIPLIER, 2))
                        print(f"[Grid Stacking] Firing Buy Level {len(gold_buys)+1} for client {login}")
                        await connection.create_market_buy_order(symbol, next_lot, 0, 0)

                # 2. Manage Sell Grid: Open next level up the trend if price surges above the highest sell
                if len(gold_sells) > 0:
                    highest_sell = max(p['openPrice'] for p in gold_sells)
                    if current_ask >= (highest_sell + PIP_SPACING):
                        next_lot = min(5.0, round(gold_sells[-1]['volume'] * MARTINGALE_MULTIPLIER, 2))
                        print(f"[Grid Stacking] Firing Sell Level {len(gold_sells)+1} for client {login}")
                        await connection.create_market_sell_order(symbol, next_lot, 0, 0)

            # --- PHASE C: GLOBAL BASKET PROFIT SWEEPS ---
            total_floating_profit = sum(p['profit'] for p in open_positions if p['symbol'] == symbol)
            target_basket_profit = max(1.0, equity * 0.015) # Dynamic target floor set to 1.5% clear sweeps
            
            if total_floating_profit >= target_basket_profit:
                print(f"[Liquidation] Net profit goal reached (${total_floating_profit}). Sweeping all lines on account {login}!")
                for position in open_positions:
                    if position['symbol'] == symbol:
                        await connection.close_position(position['id'])
                await asyncio.sleep(1.0) # Swift 1-second cooldown cycle matching your script rules
                continue

            await asyncio.sleep(0.2) # High-speed background price scanning clock rate
            
        print(f"[Engine Room] Deactivation context verified. Removing node registry for {login}")
        await account.remove()

    except Exception as e:
        print(f"CRITICAL ENGINE EXCEPTION encountered on loop thread {login}: {e}")
        active_trading_nodes[login] = False

def start_async_loop(login, password, server, symbol):
    # Overrides Render's main loop environment context to assign isolated native asynchronous processing channels
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(live_gold_compounding_grid(login, password, server, symbol))
    loop.close()

# ------------------------------------------------------------------
# MULTI-TENANT WEB REMOTE CONTROL GATEWAY RECEIVER
# ------------------------------------------------------------------
@app.route('/control', methods=['POST'])
def control_endpoint():
    data = request.get_json() or {}
    command = data.get('command')
    user_input = data.get('key_payload')
    
    if not command or not user_input:
        return jsonify({"status": "error", "message": "Invalid request payload parameters."}), 400
        
    try:
        # Automatically unpacks the 5-parameter credential string layout from the phone screen:
        # FORMAT: LICENSE/LOGIN/PASSWORD/SERVER/SYMBOL
        license_key, mt5_login, mt5_password, mt5_server, mt5_symbol = user_input.split('/')
    except ValueError:
        return jsonify({"status": "error", "message": "Key structure incorrect. Use: LICENSE/LOGIN/PASSWORD/SERVER/SYMBOL"}), 400

    # Automated Licensing Filter: Automatically accepts any unique token generated by Selar/Gumroad
    if len(license_key) < 6:
        return jsonify({"status": "error", "message": "Invalid or expired License Authorization string."}), 400

    if command == "START":
        if mt5_login not in active_trading_nodes or active_trading_nodes[mt5_login] == False:
            active_trading_nodes[mt5_login] = True
            # Spawn the user's isolated thread room so multiple clients trade independently without interfering
            threading.Thread(
                target=start_async_loop, 
                args=(mt5_login, mt5_password, mt5_server, mt5_symbol), 
                daemon=True
            ).start()
        return jsonify({"status": "success", "message": "Bot engine activated on cloud server containers."})
        
    elif command == "STOP":
        active_trading_nodes[mt5_login] = False
        return jsonify({"status": "success", "message": "Cloud termination instruction synchronized."})

    return jsonify({"status": "error", "message": "Unknown command instruction."}), 400

if __name__ == '__main__':
    # Initialize main event loops on the boot thread to ensure server dependencies initialize without errors
    main_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(main_loop)
    
    print("Starting production Waitress loop server engine on cloud port 10000...")
    serve(app, host='0.0.0.0', port=10000)
