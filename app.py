import os
import time
import asyncio
import threading
import datetime
from flask import Flask, request, jsonify
from metaapi_cloud_sdk import MetaApi
from waitress import serve

app = Flask(__name__)

# --- SECURE CREDENTIAL RECEPTACLES ---
TELEGRAM_TOKEN = "8926217564:AAFUiGwHb3PNFT8pIsTAWXsKlQG92UeojPA
"
METAAPI_TOKEN = "eyJhbGciOiJSUzUxMiIsInR5cCI6IkpXVCJ9.eyJfaWQiOiI3NTQ4ZGE1ODFjMzY1YTQzN2E1MjA5ODU0MTZhNThhNyIsImFjY2Vzc1J1bGVzIjpbeyJpZCI6InRyYWRpbmctYWNjb3VudC1tYW5hZ2VtZW50LWFwaSIsIm1ldGhvZHMiOlsidHJhZGluZy1hY2NvdW50LW1hbmFnZW1lbnQtYXBpOnJlc3Q6cHVibGljOio6KiJdLCJyb2xlcyI6WyJyZWFkZXIiLCJ3cml0ZXIiXSwicmVzb3VyY2VzIjpbIio6JFVTRVJfSUQkOioiXX0seyJpZCI6Im1ldGFhcGktcmVzdC1hcGkiLCJtZXRob2RzIjpbIm1ldGFhcGktYXBpOnJlc3Q6cHVibGljOio6KiJdLCJyb2xlcyI6WyJyZWFkZXIiLCJ3cml0ZXIiXSwicmVzb3VyY2VzIjpbIio6JFVTRVJfSUQkOioiXX0seyJpZCI6Im1ldGFhcGktcnBjLWFwaSIsIm1ldGhvZHMiOlsibWV0YWFwaS1hcGk6d3M6cHVibGljOio6KiJdLCJyb2xlcyI6WyJyZWFkZXIiLCJ3cml0ZXIiXSwicmVzb3VyY2VzIjpbIio6JFVTRVJfSUQkOioiXX0seyJpZCI6Im1ldGFhcGktcmVhbC10aW1lLXN0cmVhbWluZy1hcGkiLCJtZXRob2RzIjpbIm1ldGFhcGktYXBpOndzOnB1YmxpYzoqOioiXSwicm9sZXMiOlsicmVhZGVyIiwid3JpdGVyIl0sInJlc291cmNlcyI6WyIqOiRVU0VSX0lEJDoqIl19LHsiaWQiOiJtZXRhc3RhdHMtYXBpIiwibWV0aG9kcyI6WyJtZXRhc3RhdHMtYXBpOnJlc3Q6cHVibGljOio6KiJdLCJyb2xlcyI6WyJyZWFkZXIiLCJ3cml0ZXIiXSwicmVzb3VyY2VzIjpbIio6JFVTRVJfSUQkOioiXX0seyJpZCI6InJpc2stbWFuYWdlbWVudC1hcGkiLCJtZXRob2RzIjpbInJpc2stbWFuYWdlbWVudC1hcGk6cmVzdDpwdWJsaWM6KjoqIl0sInJvbGVzIjpbInJlYWRlciIsIndyaXRlciJdLCJyZXNvdXJjZXMiOlsiKjokVVNFUl9JRCQ6KiJdfSx7ImlkIjoiY29weWZhY3RvcnktYXBpIiwibWV0aG9kcyI6WyJjb3B5ZmFjdG9yeS1hcGk6cmVzdDpwdWJsaWM6KjoqIl0sInJvbGVzIjpbInJlYWRlciIsIndyaXRlciJdLCJyZXNvdXJjZXMiOlsiKjokVVNFUl9JRCQ6KiJdfSx7ImlkIjoibXQtbWFuYWdlci1hcGkiLCJtZXRob2RzIjpbIm10LW1hbmFnZXItYXBpOnJlc3Q6ZGVhbGluZzoqOioiLCJtdC1tYW5hZ2VyLWFwaTpyZXN0OnB1YmxpYzoqOioiXSwicm9sZXMiOlsicmVhZGVyIiwid3JpdGVyIl0sInJlc291cmNlcyI6WyIqOiRVU0VSX0lEJDoqIl19LHsiaWQiOiJiaWxsaW5nLWFwaSIsIm1ldGhvZHMiOlsiYmlsbGluZy1hcGk6cmVzdDpwdWJsaWM6KjoqIl0sInJvbGVzIjpbInJlYWRlciJdLCJyZXNvdXJjZXMiOlsiKjokVVNFUl9JRCQ6KiJdfV0sImlnbm9yZVJhdGVMaW1pdHMiOmZhbHNlLCJ0b2tlbklkIjoiMjAyMTAyMTMiLCJpbXBlcnNvbmF0ZWQiOmZhbHNlLCJyZWFsVXNlcklkIjoiNzU0OGRhNTgxYzM2NWE0MzdhNTIwOTg1NDE2YTU4YTciLCJpYXQiOjE3OTI4NjM5MTEsImV4cCI6MTgwMDYzOTkxMX0.erA0_aOLYnZLKKF3fl7pqSweGKTvMc7W70o6moKhQwn3a1Ax7J6XDs1cjJ510nfQMvinvQl4z4BegW6FcUp2JHyF7An8zLjdFTSq8MBS_nY2BjxzscSovvLZK_wHx6QpZWIguM1lhIJwCjLLe-eoz16rj7QCXGoroTrdjTzuba-wEiEw7y4VSks6cTpkwchzrtI0dMf6H2FiIDGiP7aCl51hm7FaIiyqfDbrlQi9t2oAPekBd5lBCB_doQgVDLnktsD4oKQDE4G_2hkt-TkBWggsQ3izpaRS6LaloWzHdWt1saYcFjzyNVa8a2H99XWVzix3uF7byGWi2aRUpN83SuP0o0od5jqtHeSD3eB9sH1TGXmUIPA6jLmzYZGlx8wJIstgmIlvnsfIFYGzqJ1cWiTPaRr8BJd9aho36Q_xvyqERLIfoZHV2mrp5d0_NujVVNykA8g1oxX9OeiKKH7hjZyDp9WVo6j9XZawpx2OC-fVwFfcqsZfmM8lWOB_JL3w-CItEr2D9nKOEW6TyQRf_ZnOSOGvPWSVYvF1j3xZBhbsXIvji9TfgsWFdAo0ZT6JCXl10nao431677miA5p41mi0kl2ofxtLJqIU5PZHjzEv1fjf61_Em8d1s6CeOIu_cvO0ZkgSOgoigyfgr68HmDFcvz6yVDb49gH79HKUvLQ"
# We initialize this inside our safe runtime thread setup later to prevent boot crashes
metaapi = None 

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
    global metaapi
    print(f"[Engine] Deploying grid path for account: {login}")
    try:
        if metaapi is None:
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
                        print(f"[Grid Entry] Deploying high-aggression trade layer for user {login}")
                        await connection.create_market_buy_order('XAUUSD', calculated_volume, 0, 0)
                        
            await asyncio.sleep(0.4)
            
        print(f"[Engine] Stop clicked. Deallocating terminal context for {login}")
        await account.remove()

    except Exception as e:
        print(f"Error on execution loop node {login}: {e}")
        active_trading_nodes[login] = False

def start_async_loop(login, password):
    # This completely overrides Render's thread framework and builds a fresh, isolated native event channel
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(live_gold_compounding_grid(login, password))
    loop.close()

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
            threading.Thread(target=start_async_loop, args=(mt5_login, mt5_password), daemon=True).start()
        return jsonify({"status": "success", "message": "Bot engine activated in cloud."})
        
    elif command == "STOP":
        active_trading_nodes[mt5_login] = False
        return jsonify({"status": "success", "message": "Bot engine deactivated safely."})

    return jsonify({"status": "error", "message": "Unknown command."}), 400

if __name__ == '__main__':
    # Force initialize a default event loop on the main startup thread so libraries don't panic
    main_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(main_loop)
    
    print("Starting production Waitress loop server on port 10000...")
    serve(app, host='0.0.0.0', port=10000)
