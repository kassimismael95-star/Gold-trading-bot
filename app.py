import time
import requests
import asyncio
import threading
from flask import Flask, request, jsonify
from metaapi_cloud_sdk import MetaApi

app = Flask(__name__)

# --- SECURE API RECEPTACLES ---
TELEGRAM_TOKEN = "PASTE_YOUR_TELEGRAM_BOT_TOKEN_FROM_BOTFATHER"
METAAPI_TOKEN = "PASTE_YOUR_METAAPI_TOKEN"
metaapi = MetaApi(METAAPI_TOKEN)

# Memory matrix tracking running users
active_trading_accounts = {}

async def standard_gold_grid_engine(login, password):
    print(f"[Cloud Engine] Launching Gold grid session for account: {login}")
    try:
        # Securely build a virtual desktop terminal session in the cloud
        account = await metaapi.metatrader_account_api.create_account({
            'name': f"User_{login}",
            'type': 'cloud',
            'login': login,
            'password': password,
            'server': "Exness-MT5Real9",  # Hardcoded default broker network server
            'platform': 'mt5',
            'magic': 9911
        })
        
        await account.wait_connected()
        connection = account.get_streaming_connection()
        await connection.connect()
        await connection.wait_synchronized()
        
        # Notify the user on Telegram that their bot is safely running in the cloud
        msg_url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
        # In a full setup, you would pass the user's chat_id here
        
        # --- THE CONTINUOUS STACKING ARROW WALL LOOP ---
        while active_trading_accounts.get(login) == True:
            account_info = account.account_information
            equity = account_info['equity']
            
            # v65 Risk-Based Sizing: 1 micro-lot per every $5.00 of account equity
            calculated_lots = max(0.01, round((equity / 5.0) * 0.01, 2))
            
            terminal_state = connection.terminal_state
            price = terminal_state.price('XAUUSD')
            
            if price:
                open_positions = terminal_state.positions
                gold_basket = [p for p in open_positions if p['symbol'] == 'XAUUSD']
                
                # Global Basket Profit Tracker
                total_profit = sum(p['profit'] for p in gold_basket)
                target_profit = equity * 0.01  # Cash out target set to 1% net equity gains
                
                if len(gold_basket) > 0 and total_profit >= target_profit:
                    print(f"Basket target cleared (${total_profit}). Sweeping all lines.")
                    for position in gold_basket:
                        await connection.close_position(position['id'])
                    await asyncio.sleep(12)  # Cooldown phase
                    continue

                # Continuous Micro Stacking Trigger
                if len(gold_basket) < 5:  # Absolute safety position ceiling limit
                    if (price['ask'] - price['bid']) <= 0.45:  # Spread guard filter rule
                        print("[Grid] Stacking next position layer down the trend.")
                        await connection.create_market_buy_order('XAUUSD', calculated_lots, 0, 0)
                        
            await asyncio.sleep(0.5)  # Fast-processing engine heartbeat frequency
            
        print(f"[Cloud Engine] Stop button clicked. Deleting connection for {login}")
        await account.remove()

    except Exception as e:
        print(f"Error executing trading node for account {login}: {e}")
        active_trading_accounts[login] = False

def run_async_loop(login, password):
    asyncio.run(standard_gold_grid_engine(login, password))

@app.route('/control', methods=['POST'])
def web_control_gateway():
    data = request.get_json()
    action = data.get('command')  # Expects "START" or "STOP"
    login = data.get('login')
    password = data.get('password')
    
    if action == "START":
        if login not in active_trading_accounts or active_trading_accounts[login] == False:
            active_trading_accounts[login] = True
            threading.Thread(target=run_async_loop, args=(login, password), daemon=True).start()
            
    elif action == "STOP":
        active_trading_accounts[login] = False
        
    return jsonify({"status": "success", "current_state": action})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
