import os
import sys
import json
import sqlite3
import asyncio
import threading
import datetime
import traceback
import functools
from collections import deque
from flask import Flask, request, jsonify
from flask_cors import CORS
from metaapi_cloud_sdk import MetaApi
from waitress import serve

print = functools.partial(print, flush=True)

app = Flask(__name__)

# ============================================================
# CORS CONFIGURATION
# ============================================================
CORS(app, resources={r"/*": {"origins": "*"}})

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, HEAD"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, x-api-key, X-Requested-With, Accept"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response

# ============================================================
# MASTER LICENSE & SECURITY CONFIGURATION
# ============================================================
METAAPI_TOKEN = os.environ.get("METAAPI_TOKEN", "").strip()
ALLOWED_LICENSES = ["BOSSMODE98", "BOSSMODE99"]
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.db")

metaapi_instance = None
metaapi_lock = threading.Lock()

active_trading_nodes = {}
trading_threads = {}
live_account_telemetry = {}

# ============================================================
# FIXED METAAPI ACCOUNT BINDING
# ============================================================
FIXED_METAAPI_ACCOUNT_ID = "28ecb0a9-55bf-4bd4-9d8c-cbc62b8c45ef"

# ============================================================
# HYBRID STYLE 1 + STYLE 4 SCALPING PARAMETERS
# ============================================================
BURST_ORDER_COUNT = 8
MIN_TARGET_PROFIT_USD = 0.80
PROFIT_EQUITY_RATIO = 0.04
TRAILING_FLUSH_RATIO = 0.70
MAX_ALLOWED_SPREAD_PIPS = 25.0
MAX_ACCOUNT_DRAWDOWN_RATIO = 0.35
POLL_LATENCY_DELAY = 0.015

GRID_RECOVERY_DISTANCE_PIPS = 18.0
MARTINGALE_LOT_MULTIPLIER = 1.5
MAX_RECOVERY_STAGES = 3

# ============================================================
# CONNECTION STABILITY SETTINGS
# ============================================================
MAX_CONNECTION_ATTEMPTS = 15
CONNECTION_RETRY_DELAY = 5
SYNC_TIMEOUT_SECONDS = 30
DEPLOY_TIMEOUT_SECONDS = 60
DEPLOY_WAIT_TIMEOUT_SECONDS = 180
BROKER_CONNECT_TIMEOUT_SECONDS = 180
STREAM_CONNECT_TIMEOUT_SECONDS = 60
RECONNECT_DELAY = 5
MAX_CONSECUTIVE_CRITICAL_ERRORS = 10

# ============================================================
# DATABASE
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_credentials (
            license_key TEXT PRIMARY KEY,
            mt5_login TEXT NOT NULL,
            mt5_password TEXT NOT NULL,
            mt5_server TEXT NOT NULL,
            mt5_symbol TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def db_save_credentials(license_key, login, password, server, symbol):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO user_credentials
        (license_key, mt5_login, mt5_password, mt5_server, mt5_symbol, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(license_key) DO UPDATE SET
            mt5_login=excluded.mt5_login,
            mt5_password=excluded.mt5_password,
            mt5_server=excluded.mt5_server,
            mt5_symbol=excluded.mt5_symbol,
            updated_at=CURRENT_TIMESTAMP
    """, (
        license_key.upper(),
        str(login).strip(),
        str(password),
        str(server).strip(),
        str(symbol).strip()
    ))
    conn.commit()
    conn.close()

def db_get_credentials(license_key):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT mt5_login, mt5_password, mt5_server, mt5_symbol FROM user_credentials WHERE license_key = ?",
        (license_key.upper(),)
    )
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "mt5_login": row[0],
            "mt5_password": row[1],
            "mt5_server": row[2],
            "mt5_symbol": row[3]
        }

    return None

# ============================================================
# METAAPI CLIENT
# ============================================================
def get_metaapi_client(override_token=None):
    global metaapi_instance

    token = (override_token or METAAPI_TOKEN).strip()

    if not token:
        error_message = (
            "METAAPI_TOKEN is missing or empty. "
            "Add METAAPI_TOKEN in Render Environment Variables, then redeploy."
        )

        print(f"[TOKEN ERROR] {error_message}")
        raise ValueError(error_message)

    print(
        f"[TOKEN CHECK] MetaApi token detected: "
        f"{token[:6]}...{token[-4:]}"
    )

    with metaapi_lock:
        if metaapi_instance is None or override_token:
            metaapi_instance = MetaApi(token)

    return metaapi_instance

def calculate_dynamic_lot_size(equity, balance, free_margin):
    effective_capital = max(equity, balance)

    if effective_capital < 10.0 or free_margin < 2.0:
        return 0.01, 3 if free_margin < 5.0 else 5
    elif effective_capital < 25.0:
        return 0.01, 6
    elif effective_capital < 70.0:
        return 0.02, 6
    elif effective_capital < 200.0:
        return 0.02, 8
    elif effective_capital < 800.0:
        return 0.10, 8
    elif effective_capital < 2000.0:
        return 0.20, 8
    elif effective_capital < 5000.0:
        return 0.30, 8
    elif effective_capital < 15000.0:
        return 0.90, 8
    elif effective_capital < 50000.0:
        return 2.00, 8
    else:
        return 3.00, 8

# ============================================================
# SAFE ACCOUNT DATA READERS
# ============================================================
def safe_get_account_info(terminal_state):
    try:
        info = terminal_state.account_information or {}
        return info if isinstance(info, dict) else {}
    except Exception as error:
        print(f"[ACCOUNT INFO WARNING] {error}")
        return {}

def safe_get_positions(terminal_state):
    try:
        positions = terminal_state.positions or []
        return positions if isinstance(positions, list) else []
    except Exception as error:
        print(f"[POSITIONS WARNING] {error}")
        return []

def safe_get_price(terminal_state, symbol):
    try:
        price = terminal_state.price(symbol)
        return price if isinstance(price, dict) else {}
    except Exception as error:
        print(f"[PRICE WARNING] {error}")
        return {}

def safe_get_connection_state(connection):
    try:
        terminal_state = connection.terminal_state

        connected = getattr(terminal_state, "connected", None)

        if connected is None:
            connected = getattr(terminal_state, "connected_to_broker", None)

        if connected is None:
            connected = True

        return bool(connected)

    except Exception as error:
        print(f"[CONNECTION STATE WARNING] {error}")
        return False

# ============================================================
# SAFE GOLD SYMBOL RESOLVER
# ============================================================
async def resolve_broker_gold_symbol(connection, requested_symbol):
    requested_symbol = str(requested_symbol or "").strip()

    candidates = [
        requested_symbol,
        "XAUUSDm",
        "XAUUSD",
        "XAUUSDc",
        "XAUUSDr",
        "GOLD",
        "XAUUSD247",
        "XAUUSD.a",
        "XAUUSD.ecn"
    ]

    seen = set()
    filtered_candidates = []

    for symbol in candidates:
        if symbol and symbol not in seen:
            seen.add(symbol)
            filtered_candidates.append(symbol)

    errors = []

    for symbol in filtered_candidates:
        try:
            await connection.subscribe_to_market_data(symbol)
            await asyncio.sleep(0.20)

            price = safe_get_price(connection.terminal_state, symbol)

            if price and (price.get("ask") or price.get("bid")):
                print(
                    f"[SYMBOL VERIFIED] Using Gold symbol: '{symbol}' "
                    f"(Ask: {price.get('ask')}, Bid: {price.get('bid')})"
                )
                return symbol

            errors.append(f"{symbol}: no price returned")

        except Exception as error:
            errors.append(f"{symbol}: {error}")
            print(f"[SYMBOL CHECK FAILED] {symbol}: {error}")

    error_message = (
        "No valid Gold symbol found on this broker. "
        "Enter the exact symbol from MT5 Market Watch. "
        f"Tried: {', '.join(filtered_candidates)}. "
        f"Errors: {' | '.join(errors)}"
    )

    print(f"[SYMBOL RESOLUTION FAILED] {error_message}")
    raise ValueError(error_message)

# ============================================================
# ORDER EXECUTION
# ============================================================
async def fire_stacked_directional_burst(connection, symbol, direction, volume, count, key):
    tasks = []
    bot_signature = f"GOLD MOBILE EA [{key}]"

    for _ in range(count):
        if direction == "BUY":
            tasks.append(connection.create_market_buy_order(
                symbol=symbol,
                volume=volume,
                stop_loss=None,
                take_profit=None,
                options={"comment": bot_signature}
            ))
        else:
            tasks.append(connection.create_market_sell_order(
                symbol=symbol,
                volume=volume,
                stop_loss=None,
                take_profit=None,
                options={"comment": bot_signature}
            ))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    successful = sum(1 for result in results if not isinstance(result, Exception))

    print(f"[BURST COMPLETE] {successful}/{count} {direction} orders on {symbol} at {volume} lots.")
    return successful

async def purge_entire_basket_instantly(connection, positions):
    close_tasks = []

    for position in positions:
        if "id" in position:
            close_tasks.append(connection.close_position(position["id"]))

    if close_tasks:
        results = await asyncio.gather(*close_tasks, return_exceptions=True)
        successful = sum(1 for result in results if not isinstance(result, Exception))
        print(f"[LIQUIDATOR] Closed {successful}/{len(close_tasks)} positions.")

# ============================================================
# METAAPI ACCOUNT SELECTOR WITH FIXED BINDING
# ============================================================
async def get_or_create_metaapi_account(api, login, password, server):
    login_str = str(login).strip()
    server_str = str(server).strip()

    print(
        f"[ACCOUNT BIND] Trying fixed MetaApi account: "
        f"{FIXED_METAAPI_ACCOUNT_ID}"
    )

    try:
        account = await api.metatrader_account_api.get_account(
            FIXED_METAAPI_ACCOUNT_ID
        )

        account_login = str(getattr(account, "login", "")).strip()
        account_server = str(getattr(account, "server", "")).strip()
        account_state = getattr(account, "state", "")

        print(
            f"[ACCOUNT VALIDATION] Fixed account login={account_login}, "
            f"server={account_server}, state={account_state}"
        )

        if account_login != login_str:
            raise ValueError(
                f"Fixed MetaApi account login mismatch. "
                f"Expected: {login_str}, found: {account_login}"
            )

        if account_server.lower() != server_str.lower():
            print(
                f"[SERVER MISMATCH WARNING] MetaApi account server is "
                f"'{account_server}', but Mini App sent '{server_str}'. "
                f"Using the MetaApi account server."
            )

        if account_state != "DEPLOYED":
            print(
                f"[DEPLOYING ACCOUNT] Deploying MetaApi account "
                f"{FIXED_METAAPI_ACCOUNT_ID}..."
            )

            await asyncio.wait_for(
                account.deploy(),
                timeout=DEPLOY_TIMEOUT_SECONDS
            )

            await asyncio.wait_for(
                account.wait_deployed(),
                timeout=DEPLOY_WAIT_TIMEOUT_SECONDS
            )

        print(
            f"[ACCOUNT BOUND] Using fixed MetaApi account: "
            f"{FIXED_METAAPI_ACCOUNT_ID}"
        )

        return account

    except Exception as fixed_bind_error:
        print(
            f"[DIRECT BIND ERROR] {fixed_bind_error}. "
            f"Searching existing MetaApi accounts..."
        )

    try:
        if hasattr(
            api.metatrader_account_api,
            "get_accounts_with_classic_pagination"
        ):
            response = await api.metatrader_account_api.get_accounts_with_classic_pagination()
            accounts = response.get("items", []) if isinstance(response, dict) else response
        elif hasattr(api.metatrader_account_api, "get_accounts"):
            accounts = await api.metatrader_account_api.get_accounts()
        else:
            accounts = []

        matching_accounts = []

        for account in accounts:
            account_login = str(getattr(account, "login", "")).strip()

            if account_login == login_str:
                matching_accounts.append(account)

        print(
            f"[ACCOUNT SEARCH] Found {len(matching_accounts)} MetaApi "
            f"account(s) for login {login_str}."
        )

        for account in matching_accounts:
            if getattr(account, "state", "") == "DEPLOYED":
                print(
                    f"[ACCOUNT BOUND] Reusing deployed MetaApi account: "
                    f"{getattr(account, 'id', '')}"
                )
                return account

        for account in matching_accounts:
            if getattr(account, "state", "") != "DEPLOYED":
                print(
                    f"[ACCOUNT DEPLOYING] Deploying existing MetaApi account: "
                    f"{getattr(account, 'id', '')}"
                )

                await asyncio.wait_for(
                    account.deploy(),
                    timeout=DEPLOY_TIMEOUT_SECONDS
                )

                await asyncio.wait_for(
                    account.wait_deployed(),
                    timeout=DEPLOY_WAIT_TIMEOUT_SECONDS
                )

                return account

    except Exception as search_error:
        print(f"[ACCOUNT SEARCH ERROR] {search_error}")

    print("[ACCOUNT CREATE] Creating new MetaApi account.")

    return await api.metatrader_account_api.create_account({
        "name": f"Node_{login_str}",
        "type": "cloud",
        "login": login_str,
        "password": password,
        "server": server_str,
        "platform": "mt5",
        "magic": 9924102
    })

# ============================================================
# TIMEOUT-PROTECTED CONNECTION MANAGER
# ============================================================
async def connect_metaapi_account(account, login):
    last_error = None

    for attempt in range(1, MAX_CONNECTION_ATTEMPTS + 1):
        try:
            account_id = getattr(account, "id", "unknown")
            account_state = getattr(account, "state", "unknown")

            print(
                f"[CONNECTION ATTEMPT {attempt}/{MAX_CONNECTION_ATTEMPTS}] "
                f"Connecting MT5 account {login} | MetaApi ID: {account_id} | "
                f"State: {account_state}"
            )

            if account_state != "DEPLOYED":
                print(
                    f"[DEPLOYING ACCOUNT] MetaApi account {account_id} "
                    f"is {account_state}."
                )

                try:
                    await asyncio.wait_for(
                        account.deploy(),
                        timeout=DEPLOY_TIMEOUT_SECONDS
                    )
                except Exception as deploy_error:
                    print(f"[DEPLOY WARNING] {deploy_error}")

                try:
                    await asyncio.wait_for(
                        account.wait_deployed(),
                        timeout=DEPLOY_WAIT_TIMEOUT_SECONDS
                    )

                    print(
                        f"[ACCOUNT DEPLOYED] MetaApi account {account_id} deployed."
                    )

                except Exception as deploy_wait_error:
                    print(f"[DEPLOY WAIT FAILED] {deploy_wait_error}")
                    raise deploy_wait_error

            print(
                f"[WAITING FOR BROKER] Waiting for MT5 account "
                f"{login} to connect..."
            )

            await asyncio.wait_for(
                account.wait_connected(),
                timeout=BROKER_CONNECT_TIMEOUT_SECONDS
            )

            print(
                f"[BROKER CONNECTED] MT5 account {login} connected "
                f"through MetaApi."
            )

            connection = account.get_streaming_connection()

            print(
                f"[OPENING STREAM] Opening MetaApi streaming connection "
                f"for {login}..."
            )

            await asyncio.wait_for(
                connection.connect(),
                timeout=STREAM_CONNECT_TIMEOUT_SECONDS
            )

            print(
                f"[STREAM OPEN] MetaApi streaming connection opened "
                f"for {login}."
            )

            print(
                f"[WAITING FOR SYNC] Waiting for MetaApi synchronization..."
            )

            await asyncio.wait_for(
                connection.wait_synchronized(),
                timeout=SYNC_TIMEOUT_SECONDS
            )

            print(
                f"[CORE LIVE & SYNCHRONIZED] Connected account: {login} | "
                f"MetaApi ID: {account_id}"
            )

            return connection

        except Exception as error:
            last_error = error

            print(
                f"[CONNECTION FAILED] Attempt {attempt}/{MAX_CONNECTION_ATTEMPTS}: {error}"
            )

            if attempt < MAX_CONNECTION_ATTEMPTS:
                print(
                    f"[RETRYING] Waiting {CONNECTION_RETRY_DELAY} seconds "
                    f"before retry..."
                )

                await asyncio.sleep(CONNECTION_RETRY_DELAY)

    raise Exception(
        f"Failed to connect MetaApi account {login} after "
        f"{MAX_CONNECTION_ATTEMPTS} attempts. Last error: {last_error}"
    )

# ============================================================
# MOMENTUM TRACKER
# ============================================================
class InstantCandleTracker:
    def __init__(self, max_ticks=30):
        self.ticks = deque(maxlen=max_ticks)
        self.candle_open = None
        self.last_minute = None

    def record_tick(self, price):
        current_minute = datetime.datetime.now(datetime.timezone.utc).minute

        if self.last_minute != current_minute or self.candle_open is None:
            self.candle_open = price
            self.last_minute = current_minute

        self.ticks.append(price)

    def determine_bias(self):
        if len(self.ticks) < 4:
            return "BUY"

        recent_delta = self.ticks[-1] - self.ticks[-4]
        overall_delta = self.ticks[-1] - self.ticks[0]
        candle_delta = (self.ticks[-1] - self.candle_open) if self.candle_open else 0.0

        score = 0

        if recent_delta > 0:
            score += 2
        elif recent_delta < 0:
            score -= 2

        if overall_delta > 0:
            score += 1
        elif overall_delta < 0:
            score -= 1

        if candle_delta > 0:
            score += 1
        elif candle_delta < 0:
            score -= 1

        return "BUY" if score >= 0 else "SELL"

# ============================================================
# RESILIENT TRADING ENGINE
# ============================================================
async def high_frequency_trading_engine(login, password, server, symbol, key, token=None):
    print(
        f"[HYBRID ENGINE INITIALIZED] Connecting account {login} "
        f"on {server}..."
    )

    account = None
    connection = None
    candle_tracker = InstantCandleTracker()
    current_stage = 1
    last_burst_entry_price = 0.0
    active_burst_direction = "BUY"
    peak_basket_profit = 0.0
    critical_errors = 0

    def update_telemetry(
        connected,
        active_symbol,
        balance=0,
        equity=0,
        free_margin=0,
        margin_level=0,
        floating_pnl=0,
        positions_count=0,
        price_data=None,
        error=None
    ):
        telemetry = {
            "connected_to_broker": connected,
            "balance": balance,
            "equity": equity,
            "free_margin": free_margin,
            "margin_level": margin_level,
            "floating_pnl": round(floating_pnl, 2),
            "open_positions_count": positions_count,
            "active_symbol": active_symbol,
            "active_stage": current_stage,
            "symbol_price": price_data or {},
            "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        if error:
            telemetry["error"] = error

        live_account_telemetry[str(login)] = telemetry

    update_telemetry(
        connected=False,
        active_symbol=symbol
    )

    try:
        while active_trading_nodes.get(str(login), False):
            try:
                api = get_metaapi_client(token)

                account = await get_or_create_metaapi_account(
                    api,
                    login,
                    password,
                    server
                )

                connection = await connect_metaapi_account(account, login)

                try:
                    active_symbol = await resolve_broker_gold_symbol(
                        connection,
                        symbol
                    )
                except Exception as symbol_error:
                    print(f"[CRITICAL SYMBOL ERROR] {symbol_error}")

                    update_telemetry(
                        connected=False,
                        active_symbol=symbol,
                        error=str(symbol_error)
                    )

                    return

                critical_errors = 0

                while active_trading_nodes.get(str(login), False):
                    try:
                        terminal_state = connection.terminal_state

                        account_info = safe_get_account_info(terminal_state)

                        equity = float(account_info.get("equity", 0) or 0)
                        balance = float(account_info.get("balance", 0) or 0)
                        free_margin = float(account_info.get("freeMargin", 0) or 0)
                        margin_level = float(account_info.get("marginLevel", 0) or 0)

                        broker_connected = safe_get_connection_state(connection)

                        price = safe_get_price(terminal_state, active_symbol)

                        if not price or not price.get("bid"):
                            try:
                                await connection.subscribe_to_market_data(active_symbol)
                            except Exception as subscribe_error:
                                print(f"[SUBSCRIBE WARNING] {subscribe_error}")

                            update_telemetry(
                                connected=broker_connected,
                                active_symbol=active_symbol,
                                balance=balance,
                                equity=equity,
                                free_margin=free_margin,
                                margin_level=margin_level,
                                floating_pnl=equity - balance,
                                positions_count=0
                            )

                            await asyncio.sleep(0.5)
                            continue

                        current_ask = float(price.get("ask", 0) or 0)
                        current_bid = float(price.get("bid", 0) or 0)
                        mid_price = (current_ask + current_bid) / 2.0 if current_ask and current_bid else 0.0

                        if mid_price > 0:
                            candle_tracker.record_tick(mid_price)

                        positions = safe_get_positions(terminal_state)

                        symbol_positions = [
                            position for position in positions
                            if position.get("symbol") == active_symbol
                        ]

                        net_floating_profit = equity - balance

                        update_telemetry(
                            connected=broker_connected,
                            active_symbol=active_symbol,
                            balance=balance,
                            equity=equity,
                            free_margin=free_margin,
                            margin_level=margin_level,
                            floating_pnl=net_floating_profit,
                            positions_count=len(symbol_positions),
                            price_data={
                                "ask": current_ask,
                                "bid": current_bid
                            }
                        )

                        if not broker_connected:
                            print(
                                "[BROKER DISCONNECTED] Attempting automatic "
                                "reconnection..."
                            )

                            break

                        max_drawdown_limit = balance * MAX_ACCOUNT_DRAWDOWN_RATIO

                        if symbol_positions and net_floating_profit < -max_drawdown_limit:
                            print(
                                f"[CIRCUIT BREAKER] Drawdown limit reached: "
                                f"-{abs(net_floating_profit):.2f} USD"
                            )

                            await purge_entire_basket_instantly(
                                connection,
                                symbol_positions
                            )

                            current_stage = 1
                            peak_basket_profit = 0.0
                            last_burst_entry_price = 0.0

                            await asyncio.sleep(2.0)
                            continue

                        if symbol_positions:
                            if net_floating_profit > peak_basket_profit:
                                peak_basket_profit = net_floating_profit

                            dynamic_target = max(
                                MIN_TARGET_PROFIT_USD,
                                balance * PROFIT_EQUITY_RATIO
                            )

                            if balance < 10.0:
                                dynamic_target = max(
                                    0.50,
                                    balance * 0.12
                                )

                            if net_floating_profit >= dynamic_target:
                                print(
                                    f"[TARGET HIT] Profit {net_floating_profit:.2f} USD "
                                    f"reached target {dynamic_target:.2f} USD."
                                )

                                await purge_entire_basket_instantly(
                                    connection,
                                    symbol_positions
                                )

                                current_stage = 1
                                peak_basket_profit = 0.0
                                last_burst_entry_price = 0.0

                                await asyncio.sleep(0.05)
                                continue

                            if peak_basket_profit >= 1.50 and net_floating_profit <= (
                                peak_basket_profit * TRAILING_FLUSH_RATIO
                            ):
                                print(
                                    f"[TRAILING FLUSH] Securing profit: "
                                    f"{net_floating_profit:.2f} USD"
                                )

                                await purge_entire_basket_instantly(
                                    connection,
                                    symbol_positions
                                )

                                current_stage = 1
                                peak_basket_profit = 0.0
                                last_burst_entry_price = 0.0

                                await asyncio.sleep(0.05)
                                continue

                            if current_stage < MAX_RECOVERY_STAGES and last_burst_entry_price > 0.0:
                                if active_burst_direction == "BUY":
                                    pip_divergence = (
                                        last_burst_entry_price - current_bid
                                    ) / 0.1
                                else:
                                    pip_divergence = (
                                        current_ask - last_burst_entry_price
                                    ) / 0.1

                                if pip_divergence >= GRID_RECOVERY_DISTANCE_PIPS:
                                    current_stage += 1

                                    base_lot, burst_count = calculate_dynamic_lot_size(
                                        equity,
                                        balance,
                                        free_margin
                                    )

                                    scaled_lot = round(
                                        base_lot * (
                                            MARTINGALE_LOT_MULTIPLIER ** (current_stage - 1)
                                        ),
                                        2
                                    )

                                    print(
                                        f"[RECOVERY INJECTION] Stage {current_stage}: "
                                        f"{burst_count} orders at {scaled_lot} lots."
                                    )

                                    await fire_stacked_directional_burst(
                                        connection,
                                        active_symbol,
                                        active_burst_direction,
                                        scaled_lot,
                                        burst_count,
                                        key
                                    )

                                    last_burst_entry_price = mid_price
                                    await asyncio.sleep(0.5)
                                    continue

                        if len(symbol_positions) == 0:
                            current_stage = 1
                            peak_basket_profit = 0.0

                            current_spread_pips = round(
                                (current_ask - current_bid) / 0.1,
                                2
                            )

                            if current_spread_pips > MAX_ALLOWED_SPREAD_PIPS:
                                await asyncio.sleep(POLL_LATENCY_DELAY)
                                continue

                            active_burst_direction = candle_tracker.determine_bias()

                            base_lot, burst_count = calculate_dynamic_lot_size(
                                equity,
                                balance,
                                free_margin
                            )

                            print(
                                f"[BURST DISPATCH] Stage 1: {burst_count} orders "
                                f"at {base_lot} lots, direction {active_burst_direction}."
                            )

                            await fire_stacked_directional_burst(
                                connection,
                                active_symbol,
                                active_burst_direction,
                                base_lot,
                                burst_count,
                                key
                            )

                            last_burst_entry_price = mid_price
                            await asyncio.sleep(0.05)
                            continue

                        await asyncio.sleep(POLL_LATENCY_DELAY)

                    except Exception as trading_loop_error:
                        critical_errors += 1

                        print(
                            f"[TRADING CYCLE ERROR RECOVERED {critical_errors}] "
                            f"{trading_loop_error}"
                        )

                        update_telemetry(
                            connected=False,
                            active_symbol=symbol,
                            error=str(trading_loop_error)
                        )

                        if critical_errors >= MAX_CONSECUTIVE_CRITICAL_ERRORS:
                            print(
                                "[CRITICAL ERRORS] Restarting MetaApi connection..."
                            )

                            break

                        await asyncio.sleep(1.0)

            except Exception as connection_cycle_error:
                critical_errors += 1

                print(
                    f"[CONNECTION CYCLE ERROR RECOVERED {critical_errors}] "
                    f"{connection_cycle_error}"
                )

                update_telemetry(
                    connected=False,
                    active_symbol=symbol,
                    error=str(connection_cycle_error)
                )

                if critical_errors >= MAX_CONSECUTIVE_CRITICAL_ERRORS:
                    print(
                        "[CRITICAL ERRORS] Waiting before another connection attempt..."
                    )

                    await asyncio.sleep(10.0)
                    critical_errors = 0
                else:
                    await asyncio.sleep(RECONNECT_DELAY)

    except Exception as fatal_error:
        print(
            f"[CRITICAL ENGINE ERROR] Failed to connect account {login}: "
            f"{str(fatal_error)}"
        )

        traceback.print_exc()

        update_telemetry(
            connected=False,
            active_symbol=symbol,
            error=str(fatal_error)
        )

    finally:
        active_trading_nodes.pop(str(login), None)
        trading_threads.pop(str(login), None)

        if str(login) in live_account_telemetry:
            live_account_telemetry[str(login)]["connected_to_broker"] = False
            live_account_telemetry[str(login)]["last_updated"] = (
                datetime.datetime.now(datetime.timezone.utc).isoformat()
            )

        print(f"[ENGINE STOPPED] Worker terminated for: {login}")

def launch_async_worker_thread(login, password, server, symbol, key, token=None):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        print(
            f"[WORKER STARTED] login={login} server={server} "
            f"symbol={symbol} license={key}"
        )

        loop.run_until_complete(
            high_frequency_trading_engine(
                login,
                password,
                server,
                symbol,
                key,
                token
            )
        )

        print(f"[WORKER FINISHED NORMALLY] login={login}")

    except Exception as error:
        error_message = str(error)

        print(f"[WORKER CRASHED] login={login}")
        print(f"[WORKER ERROR] {error_message}")
        traceback.print_exc()

        live_account_telemetry[str(login)] = {
            "connected_to_broker": False,
            "balance": 0,
            "equity": 0,
            "free_margin": 0,
            "margin_level": 0,
            "floating_pnl": 0,
            "open_positions_count": 0,
            "active_symbol": symbol,
            "active_stage": 1,
            "symbol_price": {},
            "error": error_message,
            "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

    finally:
        try:
            loop.close()
        except Exception:
            pass

# ============================================================
# API ROUTES
# ============================================================
def extract_request_data(req):
    data = {}

    try:
        data = req.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}

    if not data and req.form:
        try:
            data = req.form.to_dict()
        except Exception:
            pass

    if not data and req.data:
        try:
            data = json.loads(req.data.decode("utf-8"))
        except Exception:
            pass

    if not data and req.args:
        try:
            data = req.args.to_dict()
        except Exception:
            pass

    return data or {}

@app.route("/", methods=["GET"])
def health_root():
    return jsonify({
        "status": "online",
        "service": "Gold Scalper AI Hybrid Engine",
        "mode": "Parallel Burst + Martingale Grid Recovery"
    }), 200

@app.route("/health", methods=["GET"])
@app.route("/ping", methods=["GET"])
def health_ping():
    return jsonify({
        "status": "healthy",
        "service": "Gold Scalper Engine",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }), 200

@app.route("/api/account", methods=["GET"])
@app.route("/get_credentials", methods=["GET"])
def get_account_metadata():
    license_key = request.args.get("license_key", "").strip().upper()

    if license_key in ALLOWED_LICENSES:
        credentials = db_get_credentials(license_key)

        if credentials:
            return jsonify({
                "status": "success",
                "account": {
                    "mt5_login": credentials["mt5_login"],
                    "mt5_server": credentials["mt5_server"],
                    "mt5_symbol": credentials["mt5_symbol"],
                    "has_stored_password": bool(credentials["mt5_password"])
                }
            }), 200

    return jsonify({"status": "not_found"}), 200

@app.route("/status", methods=["GET", "OPTIONS"])
@app.route("/api/status", methods=["GET", "OPTIONS"])
def status_endpoint():
    active_accounts = [
        login for login, running in active_trading_nodes.items() if running
    ]

    return jsonify({
        "status": "online",
        "active_nodes_count": len(active_accounts),
        "active_accounts": active_accounts,
        "telemetry": live_account_telemetry
    }), 200

@app.route("/api/connection-status", methods=["GET", "OPTIONS"])
def connection_status_endpoint():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    login = request.args.get("mt5_login", "").strip()
    telemetry = live_account_telemetry.get(login, {})

    return jsonify({
        "status": "online",
        "mt5_login": login,
        "connected_to_broker": telemetry.get("connected_to_broker", False),
        "balance": telemetry.get("balance", 0),
        "equity": telemetry.get("equity", 0),
        "free_margin": telemetry.get("free_margin", 0),
        "floating_pnl": telemetry.get("floating_pnl", 0),
        "open_positions_count": telemetry.get("open_positions_count", 0),
        "active_symbol": telemetry.get("active_symbol", ""),
        "symbol_price": telemetry.get("symbol_price", {}),
        "last_updated": telemetry.get("last_updated", None)
    }), 200

@app.route("/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/start", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/start", methods=["GET", "POST", "OPTIONS"])
def control_dispatcher():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        data = extract_request_data(request)

        print(
            f"[START REQUEST RECEIVED] method={request.method} "
            f"path={request.path} data_keys={list(data.keys())}"
        )

        command = str(
            data.get("command") or
            data.get("action") or
            "START"
        ).strip().upper()

        license_key = str(
            data.get("license_key") or
            data.get("key") or
            "BOSSMODE99"
        ).strip().upper()

        if license_key not in ALLOWED_LICENSES:
            return jsonify({
                "status": "error",
                "success": False,
                "message": "Invalid License Key. Allowed keys: BOSSMODE98, BOSSMODE99."
            }), 200

        mt5_login = str(
            data.get("mt5_login") or
            data.get("login") or
            data.get("account") or
            ""
        ).strip()

        mt5_password = str(
            data.get("mt5_password") or
            data.get("password") or
            data.get("pass") or
            ""
        ).strip()

        mt5_server = str(
            data.get("mt5_server") or
            data.get("server") or
            data.get("broker") or
            ""
        ).strip()

        mt5_symbol = str(
            data.get("mt5_symbol") or
            data.get("symbol") or
            "XAUUSDm"
        ).strip()

        saved_credentials = db_get_credentials(license_key)

        if saved_credentials:
            mt5_login = mt5_login or saved_credentials["mt5_login"]
            mt5_password = mt5_password or saved_credentials["mt5_password"]
            mt5_server = mt5_server or saved_credentials["mt5_server"]
            mt5_symbol = mt5_symbol or saved_credentials["mt5_symbol"]

        if command == "SAVE":
            if not mt5_login or not mt5_server:
                return jsonify({
                    "status": "error",
                    "message": "Login and Server are required to save."
                }), 200

            db_save_credentials(
                license_key,
                mt5_login,
                mt5_password,
                mt5_server,
                mt5_symbol
            )

            return jsonify({
                "status": "success",
                "message": "Credentials saved securely on server database."
            }), 200

        if not mt5_login or not mt5_password or not mt5_server:
            return jsonify({
                "status": "error",
                "success": False,
                "message": "Missing credentials. Enter login, password, and server."
            }), 200

        db_save_credentials(
            license_key,
            mt5_login,
            mt5_password,
            mt5_server,
            mt5_symbol
        )

        login_str = str(mt5_login).strip()

        if command == "STOP":
            active_trading_nodes[login_str] = False

            print(f"[STOP REQUEST RECEIVED] Stopping worker for {login_str}.")

            return jsonify({
                "status": "success",
                "success": True,
                "message": "STOP command accepted. Worker will shut down safely."
            }), 200

        if command in ["START", "RUN"]:
            if active_trading_nodes.get(login_str, False):
                return jsonify({
                    "status": "success",
                    "success": True,
                    "message": "Bot is already running."
                }), 200

            active_trading_nodes[login_str] = True

            token_override = str(
                data.get("metaapi_token") or
                data.get("token") or
                request.headers.get("Authorization", "")
            ).replace("Bearer ", "").strip()

            worker = threading.Thread(
                target=launch_async_worker_thread,
                args=(
                    login_str,
                    mt5_password,
                    mt5_server,
                    mt5_symbol,
                    license_key,
                    token_override if token_override else None
                ),
                daemon=True,
                name=f"Worker-{login_str}"
            )

            trading_threads[login_str] = worker
            worker.start()

            return jsonify({
                "status": "success",
                "success": True,
                "message": f"License [{license_key}] Verified. Hybrid scalper active with Exness Gold resolution.",
                "login": login_str,
                "symbol": mt5_symbol
            }), 200

        return jsonify({
            "status": "success",
            "message": f"Command '{command}' processed."
        }), 200

    except Exception as error:
        print(f"[CONTROLLER FAULT] {error}")
        traceback.print_exc()

        return jsonify({
            "status": "error",
            "success": False,
            "message": str(error)
        }), 200

# ============================================================
# PRODUCTION ENTRYPOINT
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    print(f"[STARTUP] Running Gold Scalper AI Server on 0.0.0.0:{port}...")
    serve(app, host="0.0.0.0", port=port, threads=8)
