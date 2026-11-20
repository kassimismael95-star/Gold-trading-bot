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
active_connections = {}

# ============================================================
# ORIGINAL CORE SETTINGS
# ============================================================
MAX_ALLOWED_SPREAD_PIPS = 35.0
POLL_LATENCY_DELAY = 0.05
BURST_SPACING_DELAY = 0.08

# ============================================================
# MULTI-POSITION SCALPING SETTINGS
# ============================================================
ADD_POSITION_MOVE_USD = 0.15
MULTI_SCALP_COOLDOWN_SECONDS = 3
MAX_POSITIONS_HARD_LIMIT = 18

# ============================================================
# DYNAMIC TP / SL SETTINGS
# ============================================================
BASE_STOP_LOSS_USD = 3.00
BASE_TAKE_PROFIT_USD = 2.50
MIN_STOP_LOSS_USD = 2.00
MIN_TAKE_PROFIT_USD = 1.50
MAX_STOP_LOSS_USD = 12.00
MAX_TAKE_PROFIT_USD = 10.00

# ============================================================
# CONNECTION TIMEOUTS
# ============================================================
MAX_CONNECTION_ATTEMPTS = 5
CONNECTION_RETRY_DELAY = 5
SYNC_TIMEOUT_SECONDS = 25
DEPLOY_TIMEOUT_SECONDS = 60
DEPLOY_WAIT_TIMEOUT_SECONDS = 120
BROKER_CONNECT_TIMEOUT_SECONDS = 120
STREAM_CONNECT_TIMEOUT_SECONDS = 60

# ============================================================
# SECURE SERVER-SIDE DATABASE
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
    if not password:
        existing = db_get_credentials(license_key)

        if existing and existing.get("mt5_password"):
            password = existing["mt5_password"]

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO user_credentials (
            license_key,
            mt5_login,
            mt5_password,
            mt5_server,
            mt5_symbol,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(license_key) DO UPDATE SET
            mt5_login = excluded.mt5_login,
            mt5_password = excluded.mt5_password,
            mt5_server = excluded.mt5_server,
            mt5_symbol = excluded.mt5_symbol,
            updated_at = CURRENT_TIMESTAMP
    """, (
        license_key.upper(),
        str(login).strip(),
        password,
        server,
        symbol
    ))

    conn.commit()
    conn.close()


def db_get_credentials(license_key):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT mt5_login, mt5_password, mt5_server, mt5_symbol
        FROM user_credentials
        WHERE license_key = ?
    """, (license_key.upper(),))

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

    token = (override_token or os.environ.get("METAAPI_TOKEN", "")).strip()

    if not token:
        raise ValueError(
            "METAAPI_TOKEN is empty. "
            "Set it in Render environment variables."
        )

    with metaapi_lock:
        if metaapi_instance is None or override_token:
            metaapi_instance = MetaApi(token)

    return metaapi_instance

# ============================================================
# AGGRESSIVE EQUITY / CONFIDENCE SCALER
# ============================================================
def calculate_video_dynamic_burst(equity, balance, confidence_score):
    """
    Returns:
        first_position_lot
        max_positions_for_basket
        basket_profit_target
    """

    capital = max(equity, balance)
    abs_conf = abs(confidence_score)

    if capital < 4.0:
        max_positions = 2 if abs_conf >= 7 else 1
        return 0.01, max_positions, 0.35

    elif capital < 10.0:
        max_positions = 3 if abs_conf >= 6 else 2
        return 0.01, max_positions, 0.50

    elif capital < 25.0:
        max_positions = 5 if abs_conf >= 7 else 3
        return 0.02, max_positions, 1.00

    elif capital < 50.0:
        max_positions = 7 if abs_conf >= 6 else 5
        return 0.03, max_positions, 2.00

    elif capital < 100.0:
        max_positions = 9 if abs_conf >= 6 else 7
        return 0.04, max_positions, 4.00

    elif capital < 250.0:
        max_positions = 12 if abs_conf >= 6 else 9
        return 0.06, max_positions, 8.00

    elif capital < 500.0:
        max_positions = 14 if abs_conf >= 6 else 12
        return 0.10, max_positions, 15.00

    elif capital < 1000.0:
        max_positions = 16 if abs_conf >= 6 else 14
        return 0.20, max_positions, 30.00

    elif capital < 2000.0:
        max_positions = 18 if abs_conf >= 6 else 16
        return 0.35, max_positions, 60.00

    elif capital < 5000.0:
        max_positions = 18
        return 0.60, max_positions, 120.00

    elif capital < 10000.0:
        max_positions = 18
        return 1.00, max_positions, 250.00

    elif capital < 25000.0:
        max_positions = 18
        return 2.00, max_positions, 600.00

    else:
        max_positions = 18
        return 4.00, max_positions, 1500.00

# ============================================================
# AGGRESSIVE ADDED-POSITION LOT SIZE
# ============================================================
def calculate_added_position_lot(equity, balance, confidence_score, position_number):
    capital = max(equity, balance)
    abs_conf = abs(confidence_score)

    if capital < 10:
        base_lot = 0.01

    elif capital < 25:
        base_lot = 0.02 if abs_conf >= 7 else 0.01

    elif capital < 50:
        base_lot = 0.03 if abs_conf >= 6 else 0.02

    elif capital < 100:
        base_lot = 0.04 if abs_conf >= 6 else 0.03

    elif capital < 250:
        base_lot = 0.06 if abs_conf >= 6 else 0.04

    elif capital < 500:
        base_lot = 0.10 if abs_conf >= 6 else 0.06

    elif capital < 1000:
        base_lot = 0.20 if abs_conf >= 6 else 0.10

    elif capital < 2000:
        base_lot = 0.35 if abs_conf >= 6 else 0.20

    elif capital < 5000:
        base_lot = 0.60 if abs_conf >= 6 else 0.35

    elif capital < 10000:
        base_lot = 1.00 if abs_conf >= 6 else 0.60

    elif capital < 25000:
        base_lot = 2.00 if abs_conf >= 6 else 1.00

    else:
        base_lot = 4.00 if abs_conf >= 6 else 2.00

    if capital >= 25:
        bonus = ((position_number - 1) // 2) * 0.01
        base_lot += bonus

    return round(base_lot, 2)

# ============================================================
# DYNAMIC TP / SL CALCULATOR
# ============================================================
def calculate_dynamic_tp_sl(
    direction,
    entry_price,
    current_spread_pips,
    confidence_score,
    position_number,
    recent_price_movement
):
    """
    Creates a non-fixed TP and SL for every position.

    The SL becomes wider when:
    - Spread is wider.
    - Market movement is stronger.
    - Confidence is lower.

    The TP becomes wider when:
    - Market movement is stronger.
    - Confidence is higher.
    """

    spread_usd = current_spread_pips * 0.10

    movement_multiplier = 1.0

    if recent_price_movement > 0.50:
        movement_multiplier = 1.50
    elif recent_price_movement > 0.25:
        movement_multiplier = 1.25
    elif recent_price_movement > 0.10:
        movement_multiplier = 1.10

    confidence_multiplier = 1.0

    if confidence_score >= 8:
        confidence_multiplier = 1.20
    elif confidence_score >= 6:
        confidence_multiplier = 1.10
    elif confidence_score <= 2:
        confidence_multiplier = 0.85

    position_adjustment = (position_number - 1) * 0.10

    stop_loss_distance = (
        BASE_STOP_LOSS_USD
        + spread_usd
        + position_adjustment
    ) * movement_multiplier

    take_profit_distance = (
        BASE_TAKE_PROFIT_USD
        + (spread_usd * 0.50)
        + position_adjustment
    ) * movement_multiplier * confidence_multiplier

    stop_loss_distance = max(
        MIN_STOP_LOSS_USD,
        min(MAX_STOP_LOSS_USD, stop_loss_distance)
    )

    take_profit_distance = max(
        MIN_TAKE_PROFIT_USD,
        min(MAX_TAKE_PROFIT_USD, take_profit_distance)
    )

    if direction == "BUY":
        stop_loss = entry_price - stop_loss_distance
        take_profit = entry_price + take_profit_distance

    else:
        stop_loss = entry_price + stop_loss_distance
        take_profit = entry_price - take_profit_distance

    return {
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "stop_loss_distance": round(stop_loss_distance, 2),
        "take_profit_distance": round(take_profit_distance, 2)
    }

# ============================================================
# BUYER / SELLER MICRO-MOMENTUM TRACKER
# ============================================================
class MicroMomentumTracker:
    def __init__(self, capacity=20):
        self.ticks = deque(maxlen=capacity)
        self.candle_open = None
        self.last_minute = None

    def record_tick(self, price):
        current_minute = datetime.datetime.now(
            datetime.timezone.utc
        ).minute

        if self.last_minute != current_minute or self.candle_open is None:
            self.candle_open = price
            self.last_minute = current_minute

        self.ticks.append(price)

    def evaluate(self):
        if len(self.ticks) < 3:
            return "BUY", 6

        score = 0
        latest = self.ticks[-1]

        short_delta = latest - self.ticks[-3]

        if short_delta > 0.05:
            score += 4
        elif short_delta < -0.05:
            score -= 4
        elif short_delta > 0:
            score += 2
        elif short_delta < 0:
            score -= 2

        full_delta = latest - self.ticks[0]

        if full_delta > 0.15:
            score += 3
        elif full_delta < -0.15:
            score -= 3
        elif full_delta > 0:
            score += 1
        elif full_delta < 0:
            score -= 1

        if self.candle_open is not None:
            candle_delta = latest - self.candle_open

            if candle_delta > 0.10:
                score += 3
            elif candle_delta < -0.10:
                score -= 3
            elif candle_delta > 0:
                score += 1
            elif candle_delta < 0:
                score -= 1

        score = max(-10, min(10, score))

        direction = "BUY" if score >= 0 else "SELL"

        return direction, score

    def recent_movement(self):
        if len(self.ticks) < 3:
            return 0.0

        return abs(self.ticks[-1] - self.ticks[-3])

# ============================================================
# ORDER EXECUTION FUNCTIONS
# ============================================================
async def open_dynamic_scalp_position(
    connection,
    symbol,
    direction,
    volume,
    stop_loss,
    take_profit,
    key,
    position_number
):
    bot_signature = f"DYNAMIC-SCALP-{position_number} [{key}]"

    if direction == "BUY":
        result = await connection.create_market_buy_order(
            symbol=symbol,
            volume=volume,
            stop_loss=stop_loss,
            take_profit=take_profit,
            options={"comment": bot_signature}
        )

    else:
        result = await connection.create_market_sell_order(
            symbol=symbol,
            volume=volume,
            stop_loss=stop_loss,
            take_profit=take_profit,
            options={"comment": bot_signature}
        )

    print(
        f"[DYNAMIC POSITION OPENED] #{position_number} | "
        f"{direction} | {volume} lots | {symbol} | "
        f"SL={stop_loss} | TP={take_profit}"
    )

    return result


async def close_basket(connection, basket_positions):
    close_tasks = []

    for position in basket_positions:
        position_id = position.get("id")

        if position_id:
            close_tasks.append(
                connection.close_position(position_id)
            )

    if not close_tasks:
        print("[BASKET CLOSE] No positions to close.")
        return 0

    results = await asyncio.gather(
        *close_tasks,
        return_exceptions=True
    )

    closed_count = sum(
        1 for result in results
        if not isinstance(result, Exception)
    )

    print(
        f"[BASKET CLOSED] "
        f"{closed_count}/{len(close_tasks)} positions closed."
    )

    return closed_count

# ============================================================
# EXNESS SYMBOL RESOLVER
# ============================================================
async def resolve_broker_gold_symbol(connection, requested_symbol):
    candidates = [
        requested_symbol,
        "XAUUSDm",
        "XAUUSD",
        "XAUUSDc",
        "XAUUSDr",
        "GOLD"
    ]

    seen = set()
    filtered_candidates = []

    for symbol in candidates:
        if symbol and symbol not in seen:
            seen.add(symbol)
            filtered_candidates.append(symbol)

    for symbol in filtered_candidates:
        try:
            await connection.subscribe_to_market_data(symbol)
            await asyncio.sleep(0.15)

            price = connection.terminal_state.price(symbol)

            if price and (price.get("ask") or price.get("bid")):
                print(
                    f"[SYMBOL VERIFIED] Using verified symbol: '{symbol}'"
                )

                return symbol

        except Exception:
            continue

    await connection.subscribe_to_market_data(requested_symbol)

    return requested_symbol

# ============================================================
# SAFE METAAPI ACCOUNT RETRIEVAL
# ============================================================
def account_value(account, field, default=""):
    try:
        if isinstance(account, dict):
            return account.get(field, default)

        return getattr(account, field, default)

    except Exception:
        return default


async def get_existing_metaapi_accounts(api):
    try:
        response = await api.metatrader_account_api.get_accounts_with_infinite_scroll_pagination()

        if isinstance(response, dict):
            accounts = response.get("items", [])
        else:
            accounts = response

        return accounts or []

    except AttributeError:
        print(
            "[SDK COMPATIBILITY] Falling back to legacy get_accounts()..."
        )

        try:
            accounts = await api.metatrader_account_api.get_accounts()

            if isinstance(accounts, dict):
                return accounts.get("items", [])

            return accounts or []

        except Exception as legacy_error:
            print(
                f"[LEGACY ACCOUNT SEARCH NOTICE] {legacy_error}"
            )

            return []

    except Exception as error:
        print(f"[ACCOUNT SEARCH NOTICE] {error}")
        return []


def is_metaapi_quota_error(error_text):
    text = error_text.lower()

    return (
        "top up" in text
        or "403" in text
        or "forbidden" in text
        or "quota" in text
        or "billing" in text
    )

# ============================================================
# MULTI-ACCOUNT SAFE DEPLOYMENT
# ============================================================
async def get_or_create_metaapi_account(api, login, password, server):
    login_str = str(login).strip()
    server_str = str(server).strip()

    try:
        accounts = await get_existing_metaapi_accounts(api)

        matching_accounts = []

        for account in accounts:
            account_login = str(
                account_value(account, "login", "")
            ).strip()

            account_server = str(
                account_value(account, "server", "")
            ).strip()

            if account_login == login_str and (
                not server_str or account_server == server_str
            ):
                matching_accounts.append(account)

        print(
            f"[ACCOUNT SEARCH] Found {len(matching_accounts)} "
            f"matching MetaApi account(s) for login {login_str}."
        )

        for account in matching_accounts:
            state = str(
                account_value(account, "state", "")
            ).upper()

            if state == "DEPLOYED":
                account_id = account_value(account, "id", "")

                print(
                    f"[ACCOUNT BOUND] Reusing deployed MetaApi node: "
                    f"{account_id}"
                )

                return account

        for account in matching_accounts:
            account_id = account_value(account, "id", "")
            state = str(
                account_value(account, "state", "")
            ).upper()

            print(
                f"[ACCOUNT DEPLOYING] Deploying existing MetaApi account: "
                f"{account_id} ({state})"
            )

            try:
                await asyncio.wait_for(
                    account.deploy(),
                    timeout=DEPLOY_TIMEOUT_SECONDS
                )

                await asyncio.wait_for(
                    account.wait_deployed(),
                    timeout=DEPLOY_WAIT_TIMEOUT_SECONDS
                )

            except Exception as deploy_error:
                error_text = str(deploy_error)

                if is_metaapi_quota_error(error_text):
                    raise Exception(
                        "METAAPI BILLING BLOCKED: MetaApi refused to deploy "
                        "this trading account. Top up your MetaApi balance "
                        "or resolve the account quota restriction."
                    )

                print(f"[DEPLOY WARNING] {error_text}")

            return account

    except Exception as error:
        error_text = str(error)

        if is_metaapi_quota_error(error_text):
            raise error

        print(f"[ACCOUNT SEARCH NOTICE] {error_text}")

    print(
        f"[ACCOUNT CREATE] No matching account found. "
        f"Creating MetaApi account for {login_str}..."
    )

    try:
        new_account = await api.metatrader_account_api.create_account({
            "name": f"Node_{login_str}",
            "type": "cloud",
            "login": login_str,
            "password": password,
            "server": server_str,
            "platform": "mt5",
            "magic": 9924102,
            "reliability": "regular"
        })

        try:
            await asyncio.wait_for(
                new_account.deploy(),
                timeout=DEPLOY_TIMEOUT_SECONDS
            )

            await asyncio.wait_for(
                new_account.wait_deployed(),
                timeout=DEPLOY_WAIT_TIMEOUT_SECONDS
            )

        except Exception as deploy_error:
            error_text = str(deploy_error)

            if is_metaapi_quota_error(error_text):
                raise Exception(
                    "METAAPI BILLING BLOCKED: MetaApi refused to create or "
                    "deploy a new trading account. Top up your MetaApi "
                    "balance or resolve the restriction."
                )

            print(f"[DEPLOY WARNING] {error_text}")

        return new_account

    except Exception as create_error:
        error_text = str(create_error)

        if is_metaapi_quota_error(error_text):
            raise Exception(
                "METAAPI BILLING BLOCKED: MetaApi rejected account creation "
                "because your MetaApi balance or quota needs to be topped up."
            )

        raise create_error


async def connect_metaapi_account(account, login):
    last_error = None

    for attempt in range(1, MAX_CONNECTION_ATTEMPTS + 1):
        try:
            print(
                f"[CONNECTION ATTEMPT {attempt}/{MAX_CONNECTION_ATTEMPTS}] "
                f"Connecting MT5 account {login}..."
            )

            state = str(
                account_value(account, "state", "")
            ).upper()

            if state != "DEPLOYED":
                try:
                    await asyncio.wait_for(
                        account.deploy(),
                        timeout=DEPLOY_TIMEOUT_SECONDS
                    )

                    await asyncio.wait_for(
                        account.wait_deployed(),
                        timeout=DEPLOY_WAIT_TIMEOUT_SECONDS
                    )

                except Exception as deploy_error:
                    error_text = str(deploy_error)

                    if is_metaapi_quota_error(error_text):
                        raise Exception(
                            "METAAPI BILLING BLOCKED: MetaApi refused to "
                            "deploy this trading account."
                        )

                    print(f"[DEPLOY WARNING] {error_text}")

            await asyncio.wait_for(
                account.wait_connected(),
                timeout=BROKER_CONNECT_TIMEOUT_SECONDS
            )

            connection = account.get_streaming_connection()

            await asyncio.wait_for(
                connection.connect(),
                timeout=STREAM_CONNECT_TIMEOUT_SECONDS
            )

            try:
                await asyncio.wait_for(
                    connection.wait_synchronized(),
                    timeout=SYNC_TIMEOUT_SECONDS
                )

                print(
                    f"[CORE LIVE & SYNCHRONIZED] Connected account: {login}"
                )

                return connection

            except Exception as sync_error:
                print(
                    f"[SYNC NOTICE] Synchronization notice on attempt "
                    f"{attempt}: {sync_error}"
                )

                if attempt == MAX_CONNECTION_ATTEMPTS:
                    return connection

                await asyncio.sleep(CONNECTION_RETRY_DELAY)
                continue

        except Exception as error:
            last_error = error

            print(
                f"[CONNECTION FAILED] Attempt "
                f"{attempt}/{MAX_CONNECTION_ATTEMPTS}: {error}"
            )

            if attempt < MAX_CONNECTION_ATTEMPTS:
                await asyncio.sleep(CONNECTION_RETRY_DELAY)

    raise Exception(
        f"Failed to connect MetaApi account {login} after "
        f"{MAX_CONNECTION_ATTEMPTS} attempts: {last_error}"
    )

# ============================================================
# ORIGINAL CORE + DYNAMIC MULTI-POSITION ENGINE
# ============================================================
async def high_frequency_trading_engine(
    login,
    password,
    server,
    symbol,
    key,
    token=None
):
    print(
        f"[DYNAMIC MULTI-POSITION ENGINE INITIALIZED] "
        f"Starting trading loop for {login}..."
    )

    tracker = MicroMomentumTracker()

    last_batch_entry_price = 0.0
    last_batch_close_time = 0.0
    last_batch_direction = None

    def update_telemetry(
        connected,
        sym,
        bal=0,
        eq=0,
        f_margin=0,
        m_level=0,
        pnl=0,
        open_count=0,
        price_obj=None,
        conf=0,
        err=None
    ):
        telemetry = {
            "connected_to_broker": connected,
            "balance": bal,
            "equity": eq,
            "free_margin": f_margin,
            "margin_level": m_level,
            "floating_pnl": round(pnl, 2),
            "open_positions_count": open_count,
            "active_symbol": sym,
            "confidence_score": conf,
            "symbol_price": price_obj or {},
            "last_updated": datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat()
        }

        if err:
            telemetry["error"] = err

        live_account_telemetry[str(login)] = telemetry

    update_telemetry(False, symbol)

    try:
        api = get_metaapi_client(token)

        account = await get_or_create_metaapi_account(
            api,
            login,
            password,
            server
        )

        connection = await connect_metaapi_account(
            account,
            login
        )

        active_symbol = await resolve_broker_gold_symbol(
            connection,
            symbol
        )

        terminal_state = connection.terminal_state

        print(
            f"[CORE LIVE] Dynamic multi-position engine active "
            f"on {active_symbol}!"
        )

        while active_trading_nodes.get(str(login), False):
            try:
                account_info = terminal_state.account_information or {}

                equity = float(
                    account_info.get("equity", 0) or 0
                )

                balance = float(
                    account_info.get("balance", 0) or 0
                )

                free_margin = float(
                    account_info.get("freeMargin", 0) or 0
                )

                margin_level = float(
                    account_info.get("marginLevel", 0) or 0
                )

                broker_connected = getattr(
                    terminal_state,
                    "connected",
                    True
                )

                price = terminal_state.price(active_symbol)

                if not price or not price.get("bid"):
                    await connection.subscribe_to_market_data(
                        active_symbol
                    )

                    update_telemetry(
                        broker_connected,
                        active_symbol,
                        balance,
                        equity,
                        free_margin,
                        margin_level
                    )

                    await asyncio.sleep(0.1)
                    continue

                current_ask = float(
                    price.get("ask", 0) or 0
                )

                current_bid = float(
                    price.get("bid", 0) or 0
                )

                mid_price = (
                    current_ask + current_bid
                ) / 2.0

                tracker.record_tick(mid_price)

                recent_price_movement = tracker.recent_movement()

                positions = terminal_state.positions or []

                basket_positions = [
                    position for position in positions
                    if position.get("symbol") == active_symbol
                ]

                open_position_count = len(basket_positions)

                basket_profit = 0.0

                for position in basket_positions:
                    basket_profit += float(
                        position.get("profit", 0) or 0
                    )

                basket_profit = round(basket_profit, 2)

                net_floating_profit = equity - balance

                direction, confidence = tracker.evaluate()

                current_spread_pips = round(
                    (current_ask - current_bid) / 0.1,
                    2
                )

                update_telemetry(
                    connected=broker_connected,
                    sym=active_symbol,
                    bal=balance,
                    eq=equity,
                    f_margin=free_margin,
                    m_level=margin_level,
                    pnl=net_floating_profit,
                    open_count=open_position_count,
                    price_obj={
                        "ask": current_ask,
                        "bid": current_bid
                    },
                    conf=confidence
                )

                # ========================================================
                # BASKET PROFIT TARGET
                # ========================================================
                if open_position_count > 0:

                    lot_size, max_positions, profit_target = calculate_video_dynamic_burst(
                        equity,
                        balance,
                        confidence
                    )

                    if basket_profit >= profit_target:

                        print(
                            f"[BASKET PROFIT TARGET REACHED] "
                            f"+{basket_profit:.2f} USD | "
                            f"Target: +{profit_target:.2f} USD | "
                            f"Closing all {open_position_count} positions"
                        )

                        await close_basket(
                            connection,
                            basket_positions
                        )

                        last_batch_close_time = time.time()
                        last_batch_direction = None

                        await asyncio.sleep(
                            MULTI_SCALP_COOLDOWN_SECONDS
                        )

                        continue

                    # ====================================================
                    # ORIGINAL 35% DRAWDOWN CIRCUIT BREAKER
                    # ====================================================
                    if (
                        balance > 10.0
                        and net_floating_profit < -(balance * 0.35)
                    ):
                        print(
                            f"[CIRCUIT BREAKER] Drawdown cutoff reached: "
                            f"-{abs(net_floating_profit):.2f} USD"
                        )

                        await close_basket(
                            connection,
                            basket_positions
                        )

                        last_batch_close_time = time.time()
                        last_batch_direction = None

                        await asyncio.sleep(0.5)
                        continue

                # ========================================================
                # OPEN FIRST DYNAMIC POSITION
                # ========================================================
                if open_position_count == 0:

                    if current_spread_pips <= MAX_ALLOWED_SPREAD_PIPS:

                        first_lot, max_positions, profit_target = calculate_video_dynamic_burst(
                            equity,
                            balance,
                            confidence
                        )

                        if direction in ["BUY", "SELL"]:

                            entry_price = (
                                current_ask
                                if direction == "BUY"
                                else current_bid
                            )

                            tp_sl = calculate_dynamic_tp_sl(
                                direction,
                                entry_price,
                                current_spread_pips,
                                confidence,
                                1,
                                recent_price_movement
                            )

                            print(
                                f"[FIRST DYNAMIC ENTRY] {direction} | "
                                f"confidence={confidence} | "
                                f"lot={first_lot} | "
                                f"max_positions={max_positions} | "
                                f"SL={tp_sl['stop_loss']} | "
                                f"TP={tp_sl['take_profit']}"
                            )

                            await open_dynamic_scalp_position(
                                connection,
                                active_symbol,
                                direction,
                                first_lot,
                                tp_sl["stop_loss"],
                                tp_sl["take_profit"],
                                key,
                                1
                            )

                            last_batch_entry_price = current_price
                            last_batch_direction = direction
                            last_batch_close_time = time.time()

                            await asyncio.sleep(
                                BURST_SPACING_DELAY
                            )

                            continue

                # ========================================================
                # ADD DYNAMIC POSITIONS ONLY WHILE BASKET IS PROFITABLE
                # ========================================================
                elif (
                    open_position_count > 0
                    and open_position_count < min(
                        calculate_video_dynamic_burst(
                            equity,
                            balance,
                            confidence
                        )[1],
                        MAX_POSITIONS_HARD_LIMIT
                    )
                ):

                    lot_size, max_positions, profit_target = calculate_video_dynamic_burst(
                        equity,
                        balance,
                        confidence
                    )

                    if last_batch_direction == "BUY":
                        price_progress = (
                            current_price - last_batch_entry_price
                        )

                    elif last_batch_direction == "SELL":
                        price_progress = (
                            last_batch_entry_price - current_price
                        )

                    else:
                        price_progress = 0

                    can_add_position = (
                        basket_profit > 0
                        and price_progress >= ADD_POSITION_MOVE_USD
                        and current_spread_pips <= MAX_ALLOWED_SPREAD_PIPS
                        and free_margin > 0
                    )

                    if can_add_position:

                        added_lot = calculate_added_position_lot(
                            equity,
                            balance,
                            confidence,
                            open_position_count + 1
                        )

                        entry_price = (
                            current_ask
                            if last_batch_direction == "BUY"
                            else current_bid
                        )

                        tp_sl = calculate_dynamic_tp_sl(
                            last_batch_direction,
                            entry_price,
                            current_spread_pips,
                            confidence,
                            open_position_count + 1,
                            recent_price_movement
                        )

                        print(
                            f"[ADDING DYNAMIC POSITION] "
                            f"#{open_position_count + 1} | "
                            f"{last_batch_direction} | "
                            f"lot={added_lot} | "
                            f"basket_profit={basket_profit:.2f} | "
                            f"SL={tp_sl['stop_loss']} | "
                            f"TP={tp_sl['take_profit']}"
                        )

                        await open_dynamic_scalp_position(
                            connection,
                            active_symbol,
                            last_batch_direction,
                            added_lot,
                            tp_sl["stop_loss"],
                            tp_sl["take_profit"],
                            key,
                            open_position_count + 1
                        )

                        last_batch_entry_price = current_price

                        await asyncio.sleep(
                            BURST_SPACING_DELAY
                        )

                        continue

            except Exception as loop_error:
                print(f"[CYCLE ERROR] {loop_error}")
                await asyncio.sleep(0.5)

            await asyncio.sleep(POLL_LATENCY_DELAY)

    except Exception as error:
        error_text = str(error)

        print(
            f"[CRITICAL ENGINE ERROR] Failed to run account {login}: "
            f"{error_text}"
        )

        traceback.print_exc()

        update_telemetry(
            False,
            symbol,
            err=error_text
        )

    finally:
        active_trading_nodes.pop(str(login), None)
        trading_threads.pop(str(login), None)

        if str(login) in active_connections:
            try:
                old_connection = active_connections.pop(
                    str(login),
                    None
                )

                if old_connection:
                    await old_connection.close()

            except Exception:
                pass

        if str(login) in live_account_telemetry:
            live_account_telemetry[str(login)][
                "connected_to_broker"
            ] = False

        print(
            f"[ENGINE STOPPED] Worker terminated for: {login}"
        )


def launch_async_worker_thread(
    login,
    password,
    server,
    symbol,
    key,
    token=None
):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
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

    except Exception as error:
        print(f"[THREAD ERROR] {error}")

    finally:
        try:
            loop.close()
        except Exception:
            pass

# ============================================================
# API CONTROLLER & ROUTES
# ============================================================
def extract_request_data(req):
    data = {}

    try:
        data = req.get_json(
            force=True,
            silent=True
        ) or {}

    except Exception:
        data = {}

    if not data and req.form:
        try:
            data = req.form.to_dict()

        except Exception:
            pass

    if not data and req.data:
        try:
            data = json.loads(
                req.data.decode("utf-8")
            )

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
        "service": "Gold Dynamic Multi-Position Scalper",
        "mode": "Original Core + Dynamic TP/SL + Aggressive Lot Scaling"
    }), 200


@app.route("/health", methods=["GET"])
@app.route("/ping", methods=["GET"])
def health_ping():
    return jsonify({
        "status": "healthy",
        "service": "Gold Dynamic Multi-Position Scalper",
        "timestamp": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
    }), 200


@app.route("/api/account", methods=["GET"])
@app.route("/get_credentials", methods=["GET"])
def get_account_metadata():
    license_key = request.args.get(
        "license_key",
        ""
    ).strip().upper()

    if license_key in ALLOWED_LICENSES:
        credentials = db_get_credentials(license_key)

        if credentials:
            return jsonify({
                "status": "success",
                "account": {
                    "mt5_login": credentials["mt5_login"],
                    "mt5_server": credentials["mt5_server"],
                    "mt5_symbol": credentials["mt5_symbol"],
                    "has_stored_password": bool(
                        credentials["mt5_password"]
                    )
                }
            }), 200

    return jsonify({
        "status": "not_found"
    }), 200


@app.route("/status", methods=["GET", "OPTIONS"])
@app.route("/api/status", methods=["GET", "OPTIONS"])
def status_endpoint():
    active_accounts = [
        login for login, running in active_trading_nodes.items()
        if running
    ]

    return jsonify({
        "status": "online",
        "active_nodes_count": len(active_accounts),
        "active_accounts": active_accounts,
        "telemetry": live_account_telemetry
    }), 200


@app.route("/api/connection-status", methods=["GET", "OPTIONS"])
def connection_status_endpoint():
    login = request.args.get(
        "mt5_login",
        ""
    ).strip()

    return jsonify(
        live_account_telemetry.get(
            login,
            {
                "connected_to_broker": False
            }
        )
    ), 200


@app.route("/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/start", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/start", methods=["GET", "POST", "OPTIONS"])
def control_dispatcher():
    if request.method == "OPTIONS":
        return jsonify({
            "status": "ok"
        }), 200

    try:
        data = extract_request_data(request)

        command = str(
            data.get("command")
            or data.get("action")
            or "START"
        ).strip().upper()

        license_key = str(
            data.get("license_key")
            or data.get("key")
            or "BOSSMODE99"
        ).strip().upper()

        if license_key not in ALLOWED_LICENSES:
            return jsonify({
                "status": "error",
                "success": False,
                "message": (
                    "Invalid License Key. Allowed keys: "
                    "BOSSMODE98, BOSSMODE99."
                )
            }), 200

        mt5_login = str(
            data.get("mt5_login")
            or data.get("login")
            or data.get("account")
            or ""
        ).strip()

        mt5_password = str(
            data.get("mt5_password")
            or data.get("password")
            or data.get("pass")
            or ""
        ).strip()

        mt5_server = str(
            data.get("mt5_server")
            or data.get("server")
            or data.get("broker")
            or ""
        ).strip()

        mt5_symbol = str(
            data.get("mt5_symbol")
            or data.get("symbol")
            or "XAUUSDm"
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
                    "message": (
                        "Login and Server are required to save."
                    )
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
                "message": (
                    "Missing credentials. Enter login, password, and server."
                )
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

            return jsonify({
                "status": "success",
                "success": True,
                "message": "STOP command accepted. Worker stopping."
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
                data.get("metaapi_token")
                or data.get("token")
                or request.headers.get("Authorization", "")
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
                "message": (
                    f"License [{license_key}] Verified. "
                    f"Dynamic multi-position scalper active "
                    f"on {mt5_symbol}."
                ),
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

    print(
        f"[STARTUP] Running Gold Dynamic Multi-Position Scalper on "
        f"0.0.0.0:{port}..."
    )

    serve(
        app,
        host="0.0.0.0",
        port=port,
        threads=8
    )
