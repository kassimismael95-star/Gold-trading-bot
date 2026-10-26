import os
import time
import asyncio
import threading
import datetime
from flask import Flask, request, jsonify
from metaapi_cloud_sdk import MetaApi

app = Flask(__name__)

# --- SECURE CREDENTIAL RECEPTACLES ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
METAAPI_TOKEN = os.getenv("METAAPI_TOKEN", "")

# Active execution registry tracking running sessions
active_trading_nodes = {}

def check_market_execution_safeties():
    now = datetime.datetime.utcnow()
    day_of_week = now.weekday()  # Monday=0, Friday=4, Saturday=5, Sunday=6
    hour = now.hour
    minute = now.minute
    day_of_month = now.day

    # 1. Weekend Close Safeguard Filter (Friday 21:00 UTC through Sunday 22:00 UTC)
    if (day_of_week == 4 and hour >= 21) or (day_of_week == 5) or (day_of_week == 6 and hour < 22):
        return False

    # 2. Macro Data Blackout Filter (NFP / CPI / FOMC)
    if day_of_week == 4 and day_of_month <= 7 and hour == 13 and (15 <= minute <= 45):
        return False
    if day_of_week in [1, 2, 3] and hour == 13 and (15 <= minute <= 45):
        return False
    if day_of_week in [2, 3] and (18 <= hour <= 20):
        return False

    return True

async def live_gold_compounding_grid(login, password):
    print(f"[Engine] Deploying grid path for account: {login}")
    try:
        if not METAAPI_TOKEN:
            print("[Engine Error] METAAPI_TOKEN is missing!")
            active_trading_nodes[login] = False
            return

        # Initialize MetaApi safely inside the running event loop
        metaapi = MetaApi(METAAPI_TOKEN)

        account = await metaapi.metatrader_account_api.create_account({
            'name': f"Node_{login}",
            'type': 'cloud',
            'login': str(login),
            'password': password,
            'server': "Exness-MT5Real9",
            'platform': 'mt5',
            'magic': 774411
        })
        
        await account.wait_connected()
        connection = account.get_streaming_connection()
        await connection.connect()
        await connection.wait_synchronized()
        print(f"[Engine] Cloud system synchronized for account {login}")

        while active_trading_nodes.get(login) == True:
            if not check_market_execution_safeties():
                await asyncio.sleep(5)
                continue

            account_info = account.account_information
            equity = account_info['equity']
            
            calculated_volume = max(0.01, round((equity / 3.0) * 0.01, 2))
            
            terminal_state = connection.terminal_state
            price = terminal_state.price('XAUUSD')
            
            if price:
                open_positions = terminal_state.positions
                gold_trades = [p for p in open_positions if p['symbol'] == 'XAUUSD']
                
                total_floating_payout = sum(p['profit'] for p in gold_trades)
                target_basket_profit = max(1.0, equity * 0.015)
                
                if len(gold_trades) > 0 and total_floating_payout >= target_basket_profit:
                    print(f"[Liquidation] Target met (${total_floating_payout}). Sweeping all lines.")
                    for position in gold_trades:
                        await connection.close_position(position['id'])
                    await asyncio.sleep(15)
                    continue

                if len(gold_trades) < 6:
                    spread = price['ask'] - price['bid']
                    if spread <= 0.50:
                        print(f"[Grid Entry] Deploying trade layer for user {login}")
                        await connection.create_market_buy_order('XAUUSD', calculated_volume, 0, 0)
                        
            await asyncio.sleep(0.4)
            
        print(f"[Engine] Stop clicked. Deallocating terminal context for {login}")
        await account.remove()

    except Exception as e:
        print(f"Error on execution loop node {login}: {e}")
        active_trading_nodes[login] = False

def launch_asynchronous_loop_context(login, password):
    asyncio.run(live_gold_compounding_grid(login, password))

@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "online", "message": "Gold Scalper Engine is running."})

@app.route('/control', methods=['POST'])
def control_endpoint():
    data = request.get_json() or {}
    command = data.get('command')
    user_input = data.get('key_payload')
    
    if not command or not user_input:
        return jsonify({"status": "error", "message": "Invalid parameters."}), 400
        
    try:
        license_key, mt5_login, mt5_password = user_input.split('/')
    except ValueError:
        return jsonify({"status": "error", "message": "Key format incorrect. Use: LICENSE/LOGIN/PASSWORD"}), 400

    if command == "START":
        if mt5_login not in active_trading_nodes or active_trading_nodes[mt5_login] == False:
            active_trading_nodes[mt5_login] = True
            threading.Thread(target=launch_asynchronous_loop_context, args=(mt5_login, mt5_password), daemon=True).start()
        return jsonify({"status": "success", "message": "Bot engine activated in cloud."})
        
    elif command == "STOP":
        active_trading_nodes[mt5_login] = False
        return jsonify({"status": "success", "message": "Bot engine deactivated safely."})

    return jsonify({"status": "error", "message": "Unknown command."}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
