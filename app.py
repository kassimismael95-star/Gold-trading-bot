import os
import asyncio
import threading
import datetime
import traceback

from flask import Flask, request, jsonify
from metaapi_cloud_sdk import MetaApi
from waitress import serve

app = Flask(__name__)

# ============================================================
# ENVIRONMENT
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("BOT_TOKEN")
METAAPI_TOKEN = os.environ.get("METAAPI_TOKEN")

# ============================================================
# GLOBAL STATE
# ============================================================

metaapi = None
metaapi_lock = threading.Lock()

active_trading_nodes = {}
trading_threads = {}

# ============================================================
# GRID SETTINGS
# ============================================================

PIP_SPACING = 1.5
MARTINGALE_MULTIPLIER = 1.5

# Safety ceiling retained so an API/broker failure cannot create
# an unbounded order storm.
MAX_GRID_LEVELS = 25

# ============================================================
# MARKET SESSION
# ============================================================

def check_market_execution_safeties():
    """Return False during the normal weekend market closure."""
    now = datetime.datetime.utcnow()
    day = now.weekday()
    hour = now.hour

    if (day == 4 and hour >= 21) or day == 5 or (day == 6 and hour < 22):
        return False

    return True


# ============================================================
# METAAPI
# ============================================================

def get_metaapi_client():
    global metaapi

    if not METAAPI_TOKEN:
        raise RuntimeError("METAAPI_TOKEN environment variable is missing.")

    with metaapi_lock:
        if metaapi is None:
            metaapi = MetaApi(METAAPI_TOKEN)

    return metaapi


# ============================================================
# IMMEDIATE BASKET OPEN
# ============================================================

async def open_initial_basket(connection, symbol, volume, login):
    """
    Immediately attempt the initial BUY + SELL basket.
    The function returns after the broker accepts/rejects the
    requests; the main loop immediately continues monitoring.
    """

    buy_ok = False
    sell_ok = False

    try:
        await connection.create_market_buy_order(symbol, volume, 0, 0)
        buy_ok = True
        print(f"[ENTRY] BUY submitted: {login} {symbol} {volume}")
    except Exception as e:
        print(f"[ENTRY ERROR] BUY {login}: {e}")

    try:
        await connection.create_market_sell_order(symbol, volume, 0, 0)
        sell_ok = True
        print(f"[ENTRY] SELL submitted: {login} {symbol} {volume}")
    except Exception as e:
        print(f"[ENTRY ERROR] SELL {login}: {e}")

    return buy_ok or sell_ok


# ============================================================
# CONTINUOUS TRADING ENGINE
# ============================================================

async def live_gold_compounding_grid(login, password, server, symbol):
    print(f"[ENGINE] Starting node for {login} / {server} / {symbol}")

    account = None

    try:
        api = get_metaapi_client()

        account = await api.metatrader_account_api.create_account(
            {
                "name": f"Cloud_Node_{login}",
                "type": "cloud",
                "login": str(login),
                "password": password,
                "server": server,
                "platform": "mt5",
                "magic": 24102401,
            }
        )

        print(f"[ENGINE] Waiting for MT5 connection: {login}")
        await account.wait_connected()

        connection = account.get_streaming_connection()

        await connection.connect()
        await connection.wait_synchronized()

        print(f"[ENGINE] CONNECTED: {login}")

        # ====================================================
        # NEVER-INTENTIONALLY-IDLE TRADING LOOP
        # ====================================================

        while active_trading_nodes.get(login, False):

            if not check_market_execution_safeties():
                print(f"[SESSION] Market session closed for {login}")
                await asyncio.sleep(5)
                continue

            account_info = account.account_information or {}
            equity = float(account_info.get("equity", 0) or 0)

            # Original dynamic sizing rule.
            calculated_volume = max(
                0.01,
                round((equity / 2.0) * 0.01, 2),
            )

            terminal_state = connection.terminal_state
            price = terminal_state.price(symbol)

            if not price:
                await asyncio.sleep(0.05)
                continue

            current_ask = price.get("ask")
            current_bid = price.get("bid")

            if current_ask is None or current_bid is None:
                await asyncio.sleep(0.05)
                continue

            positions = terminal_state.positions or []

            symbol_positions = [
                p for p in positions
                if p.get("symbol") == symbol
            ]

            buys = [
                p for p in symbol_positions
                if p.get("type") == "POSITION_TYPE_BUY"
            ]

            sells = [
                p for p in symbol_positions
                if p.get("type") == "POSITION_TYPE_SELL"
            ]

            total_positions = len(buys) + len(sells)

            # =================================================
            # ZERO POSITIONS:
            # IMMEDIATELY START A NEW BASKET
            # =================================================

            if total_positions == 0:
                print(
                    f"[NEW BASKET] No {symbol} positions on {login}. "
                    f"Opening immediately."
                )

                await open_initial_basket(
                    connection,
                    symbol,
                    calculated_volume,
                    login,
                )

                # No deliberate waiting after entry.
                await asyncio.sleep(0.02)
                continue

            # =================================================
            # GRID BUY
            # =================================================

            if total_positions < MAX_GRID_LEVELS and buys:
                lowest_buy = min(
                    float(p.get("openPrice", current_bid))
                    for p in buys
                )

                if current_bid <= lowest_buy - PIP_SPACING:
                    previous_volume = float(
                        buys[-1].get("volume", calculated_volume)
                    )

                    next_lot = min(
                        5.0,
                        round(
                            previous_volume * MARTINGALE_MULTIPLIER,
                            2,
                        ),
                    )

                    try:
                        await connection.create_market_buy_order(
                            symbol,
                            next_lot,
                            0,
                            0,
                        )
                        print(
                            f"[GRID] BUY level {len(buys)+1}: "
                            f"{login} {symbol} {next_lot}"
                        )
                    except Exception as e:
                        print(f"[GRID ERROR] BUY {login}: {e}")

            # =================================================
            # GRID SELL
            # =================================================

            if total_positions < MAX_GRID_LEVELS and sells:
                highest_sell = max(
                    float(p.get("openPrice", current_ask))
                    for p in sells
                )

                if current_ask >= highest_sell + PIP_SPACING:
                    previous_volume = float(
                        sells[-1].get("volume", calculated_volume)
                    )

                    next_lot = min(
                        5.0,
                        round(
                            previous_volume * MARTINGALE_MULTIPLIER,
                            2,
                        ),
                    )

                    try:
                        await connection.create_market_sell_order(
                            symbol,
                            next_lot,
                            0,
                            0,
                        )
                        print(
                            f"[GRID] SELL level {len(sells)+1}: "
                            f"{login} {symbol} {next_lot}"
                        )
                    except Exception as e:
                        print(f"[GRID ERROR] SELL {login}: {e}")

            # =================================================
            # BASKET PROFIT
            # =================================================

            total_profit = sum(
                float(p.get("profit", 0) or 0)
                for p in symbol_positions
            )

            target_profit = max(1.0, equity * 0.015)

            if total_profit >= target_profit:
                print(
                    f"[PROFIT] Basket target reached on {login}: "
                    f"${total_profit:.2f}. Closing basket."
                )

                current_positions = [
                    p for p in (connection.terminal_state.positions or [])
                    if p.get("symbol") == symbol
                ]

                for position in current_positions:
                    try:
                        await connection.close_position(position["id"])
                    except Exception as e:
                        print(
                            f"[CLOSE ERROR] {login} "
                            f"{position.get('id')}: {e}"
                        )

                # IMPORTANT:
                # There is deliberately no long cooldown here.
                # The next loop sees zero positions and immediately
                # opens the next basket.
                await asyncio.sleep(0.02)
                continue

            # High-speed monitoring.
            await asyncio.sleep(0.05)

    except Exception as e:
        print(f"[CRITICAL ENGINE ERROR] {login}: {e}")
        traceback.print_exc()
        active_trading_nodes[login] = False

    finally:
        try:
            if account is not None:
                await account.remove()
        except Exception as e:
            print(f"[CLEANUP ERROR] {login}: {e}")

        active_trading_nodes[login] = False
        trading_threads.pop(login, None)

        print(f"[ENGINE] Node stopped: {login}")


# ============================================================
# THREAD WRAPPER
# ============================================================

def start_async_loop(login, password, server, symbol):
    loop = asyncio.new_event_loop()

    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(
            live_gold_compounding_grid(
                login,
                password,
                server,
                symbol,
            )
        )
    except Exception as e:
        print(f"[THREAD ERROR] {login}: {e}")
        traceback.print_exc()
        active_trading_nodes[login] = False
    finally:
        try:
            loop.close()
        except Exception:
            pass


# ============================================================
# HEALTH ENDPOINT
# ============================================================

@app.route("/", methods=["GET"])
def health_check():
    active = [
        login for login, running in active_trading_nodes.items()
        if running
    ]

    return jsonify(
        {
            "status": "online",
            "service": "Gold Cloud Grid Scalper",
            "active_accounts": len(active),
        }
    )


# ============================================================
# STATUS ENDPOINT
# ============================================================

@app.route("/status", methods=["GET"])
def status_endpoint():
    return jsonify(
        {
            "status": "online",
            "active_accounts": [
                login for login, running in active_trading_nodes.items()
                if running
            ],
        }
    )


# ============================================================
# CONTROL ENDPOINT
# ============================================================

@app.route("/control", methods=["POST"])
def control_endpoint():
    data = request.get_json(silent=True) or {}

    command = str(data.get("command", "")).strip().upper()
    user_input = str(data.get("key_payload", "")).strip()

    if not command or not user_input:
        return jsonify(
            {
                "status": "error",
                "message": "Invalid request payload parameters.",
            }
        ), 400

    parts = user_input.split("/")

    if len(parts) != 5:
        return jsonify(
            {
                "status": "error",
                "message": (
                    "Key structure incorrect. "
                    "Use: LICENSE/LOGIN/PASSWORD/SERVER/SYMBOL"
                ),
            }
        ), 400

    license_key, mt5_login, mt5_password, mt5_server, mt5_symbol = [
        part.strip() for part in parts
    ]

    # Preserves the original license-string behavior.
    if len(license_key) < 6:
        return jsonify(
            {
                "status": "error",
                "message": "Invalid or expired License Authorization string.",
            }
        ), 400

    if command == "START":
        if active_trading_nodes.get(mt5_login, False):
            return jsonify(
                {
                    "status": "success",
                    "message": "Bot engine is already active.",
                    "login": mt5_login,
                }
            ), 200

        active_trading_nodes[mt5_login] = True

        worker = threading.Thread(
            target=start_async_loop,
            args=(
                mt5_login,
                mt5_password,
                mt5_server,
                mt5_symbol,
            ),
            daemon=True,
            name=f"TradingNode-{mt5_login}",
        )

        trading_threads[mt5_login] = worker
        worker.start()

        print(
            f"[CONTROL] START accepted: "
            f"{mt5_login} / {mt5_symbol}"
        )

        return jsonify(
            {
                "status": "success",
                "message": "Trading engine started.",
                "login": mt5_login,
                "symbol": mt5_symbol,
            }
        ), 200

    if command == "STOP":
        active_trading_nodes[mt5_login] = False

        print(f"[CONTROL] STOP accepted: {mt5_login}")

        return jsonify(
            {
                "status": "success",
                "message": "Cloud termination instruction synchronized.",
                "login": mt5_login,
            }
        ), 200

    return jsonify(
        {
            "status": "error",
            "message": "Unknown command instruction.",
        }
    ), 400


# ============================================================
# RENDER STARTUP
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))

    print(
        f"Starting Waitress server on 0.0.0.0:{port}"
    )

    serve(
        app,
        host="0.0.0.0",
        port=port,
        threads=8,
    )
