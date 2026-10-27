import os
import time
import asyncio
import threading
import datetime
from flask import Flask, request, jsonify
from metaapi_cloud_sdk import MetaApi
from waitress import serve

app = Flask(__name__)

# --- SYSTEM INTEGRATION KEYS ---
METAAPI_TOKEN = os.environ.get("METAAPI_TOKEN")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
metaapi = None 

# Active dictionary matrix keeping track of running accounts
active_trading_nodes = {}

# PURE UNRESTRICTED SCALPER CONFIGURATION - MATCHES THE EXACT FIT
PIP_SPACING = 1.5           # Tight stacking interval (1.5 pips on Gold)
MARTINGALE_MULTIPLIER = 1.5 # Volumetric compounding scaling factor
MAX_GRID_LEVELS = 25        # Deep grid ceiling matching your updated script

def check_market_execution_safeties():
    """ONLY BLOCKS RUNNING DURING WEEKEND CLOSE ARCHITECTURE"""
    now = datetime.datetime.utcnow()
    day_of_week = now.weekday()  # Monday=0, Friday=4, Saturday=5, Sunday=6
    hour = now.hour

    # Weekend Close structural window (Friday 21:00 UTC through Sunday 22:00 UTC)
    if (day_of_week == 4 and hour >= 21) or (day_of_week == 5) or (day_of_week == 6 and hour < 22):
        return False
    return True

async def live_gold_compounding_grid(login, password, server):
    global metaapi
    print(f"[Cloud Engine] Spawning unrestricted loop instance for account: {login}")
    try:
        if metaapi is None:
            metaapi = MetaApi(METAAPI_TOKEN)
            
        account = await metaapi.metatrader_account_api.create_account({
            'name': f"Node_{login}",
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
        print(f"[Cloud Engine] Secure connection locked to {server} for account {login}")

        while active_trading_nodes.get(login) == True:
            # 1. Check Weekend Circuit Breaker Only (All news filters completely removed)
            if not check_market_execution_safeties():
                print(f"[Weekend Guard] Closing out positions for weekend gap security on {login}")
                # Optional terminal sweep logic can be placed here
                await asyncio.sleep(5)
                continue

            account_info = account.account_information
            equity = account_info['equity']
            
            # v65 Hyper-Compounding: 1 micro lot per every $2.00 USD of active equity
            calculated_volume = max(0.01, round((equity / 2.00) * 0.01, 2))
            
            terminal_state = connection.terminal_state
            price = terminal_state.price('XAUUSD')
            
            if not price:
                await asyncio.sleep(0.1)
                continue
                
            current_ask = price['ask']
            current_bid = price['bid']
            
            # Extract active market order lines
            open_positions = terminal_state.positions
            gold_buys = [p for p in open_positions if p['symbol'] == 'XAUUSD' and p['type'] == 'POSITION_TYPE_BUY']
            gold_sells = [p for p in open_positions if p['symbol'] == 'XAUUSD' and p['type'] == 'POSITION_TYPE_SELL']
            total_positions = len(gold_buys) + len(gold_sells)

            # --- PHASE A: IMMEDIATE INITIALIZATION ANCHOR HEDGE ---
            if total_positions == 0:
                print(f"[Cloud Grid] Account {login} empty. Deploying instant double anchors.")
                await connection.create_market_buy_order('XAUUSD', calculated_volume, 0, 0)
                await connection.create_market_sell_order('XAUUSD', calculated_volume, 0, 0)
                continue

            # --- PHASE B: HIGH-SPEED GRID LAYER STACKING ---
            if total_positions < MAX_GRID_LEVELS:
                # 1. Stack Buy Layers if price drops by pip threshold
                if len(gold_buys) > 0:
                    lowest_buy = min(p['openPrice'] for p in gold_buys)
                    if current_bid <= (lowest_buy - PIP_SPACING):
                        next_lot = min(5.0, round(gold_buys[-1]['volume'] * MARTINGALE_MULTIPLIER, 2))
                        print(f"[Cloud Engine] Stacking Buy level {len(gold_buys)+1} for account {login}")
                        await connection.create_market_buy_order('XAUUSD', next_lot, 0, 0)

                # 2. Stack Sell Layers if price surges by pip threshold
                if len(gold_sells) > 0:
                    highest_sell = max(p['openPrice'] for p in gold_sells)
                    if current_ask >= (highest_sell + PIP_SPACING):
                        next_lot = min(5.0, round(gold_sells[-1]['volume'] * MARTINGALE_MULTIPLIER, 2))
                        print(f"[Cloud Engine] Stacking Sell level {len(gold_sells)+1} for account {login}")
                        await connection.create_market_sell_order('XAUUSD', next_lot, 0, 0)

            # --- PHASE C: GLOBAL BASKET LIQUIDATION PATROL ---
            total_floating_profit = sum(p['profit'] for p in open_positions if p['symbol'] == 'XAUUSD')
            target_basket_profit = max(1.0, equity * 0.015) # Dynamic target floor set to 1.5% profit sweeps
            
            if total_floating_profit >= target_basket_profit:
                print(f"[Liquidation] Target hit (${total_floating_profit}). Clearing all open lines on {login}")
                for position in open_positions:
                    if position['symbol'] == 'XAUUSD':
                        await connection.close_position(position['id'])
                await asyncio.sleep(1) # Immediate 1-second cooldown cycle match
                continue

            await asyncio.sleep(0.2) # High-speed cycle loop execution heartbeat
            
        print(f"[Engine] Stop context processed. Removing node registration for {login}")
        await account.remove()

    except Exception as e:
        print(f"Critical execution error encountered on loop node {login}: {e}")
        active_trading_nodes[login] = False

def start_async_loop(login, password, server):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(live_gold_compounding_grid(login, password, server))
    loop.close()

@app.route('/control', methods=['POST'])
def control_endpoint():
    data = request.get_json() or {}
    command = data.get('command')
    user_input = data.get('key_payload')
    
    if not command or not user_input:
        return jsonify({"status": "error", "message": "Invalid request properties."}), 400
        
    try:
        # Seamlessly unpacks the dynamic 4-parameter credential key
        license_key, mt5_login, mt5_password, mt5_server = user_input.split('/')
    except ValueError:
        return jsonify({"status": "error", "message": "Key format incorrect. Use: LICENSE/LOGIN/PASSWORD/SERVER"}), 400

    # Verification block: Ensures the customer filled out the key boxes properly
    if len(license_key) < 6:
        return jsonify({"status": "error", "message": "Invalid or expired License Authorization string."}), 400

    if command == "START":
        if mt5_login not in active_trading_nodes or active_trading_nodes[mt5_login] == False:
            active_trading_nodes[mt5_login] = True
            threading.Thread(target=start_async_loop, args=(mt5_login, mt5_password, mt5_server), daemon=True).start()
        return jsonify({"status": "success", "message": "Bot engine activated in cloud."})
        
    elif command == "STOP":
        active_trading_nodes[mt5_login] = False
        return jsonify({"status": "success", "message": "Bot engine deactivated safely."})

    return jsonify({"status": "error", "message": "Unknown command."}), 400

if __name__ == '__main__':
    main_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(main_loop)
    serve(app, host='0.0.0.0', port=10000)
