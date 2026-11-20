import os
import time
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
# MASTER LICENSE & SECURITY
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
# GHOST ADAPTIVE QUALITY INDIVIDUAL-TP SCALPER
# ============================================================
MAX_ALLOWED_SPREAD_PIPS = 25.0
POLL_LATENCY_DELAY = 0.05
FAST_REENTRY_COOLDOWN_SECONDS = 2.0
ADD_POSITION_MOVE_USD = 0.15

# Quality-based adaptive TP / SL
BASE_STOP_LOSS_DISTANCE_USD = 0.80
MIN_STOP_LOSS_DISTANCE_USD = 0.50
MAX_STOP_LOSS_DISTANCE_USD = 1.50

STRONG_TP_RR = 1.50
NORMAL_TP_RR = 1.20
WEAK_TP_RR = 1.00

DAILY_LOSS_LIMIT_PERCENT = 0.0
MAX_CONSECUTIVE_LOSSES = 0

M5_RANGE_LOOKBACK = 20
M5_REJECTION_BUFFER = 0.50

# Connection Timeouts
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
        INSERT INTO user_credentials (license_key, mt5_login, mt5_password, mt5_server, mt5_symbol, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(license_key) DO UPDATE SET
            mt5_login=excluded.mt5_login,
            mt5_password=excluded.mt5_password,
            mt5_server=excluded.mt5_server,
            mt5_symbol=excluded.mt5_symbol,
            updated_at=CURRENT_TIMESTAMP
    """, (license_key.upper(), str(login).strip(), password, server, symbol))
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
def get_metaapi_client(override_token: str = None):
    global metaapi_instance
    token = (override_token or os.environ.get("METAAPI_TOKEN", "")).strip()

    if not token:
        raise ValueError("METAAPI_TOKEN is empty. Set it in Render environment variables.")

    with metaapi_lock:
        if metaapi_instance is None or override_token:
            metaapi_instance = MetaApi(token)

    return metaapi_instance

# ============================================================
# DYNAMIC EQUITY-BASED SCALP PLAN
# ============================================================
def calculate_dynamic_scalp_plan(equity, balance, entry_quality_score):
    capital = max(equity, balance)
    score = entry_quality_score

    if capital < 4.0:
        return 0.01, 2

    elif capital < 10.0:
        if score <= 3:
            return 0.01, 2
        elif score <= 6:
            return 0.01, 2
        else:
            return 0.02, 3

    elif capital < 25.0:
        if score <= 3:
            return 0.01, 3
        elif score <= 6:
            return 0.02, 4
        else:
            return 0.02, 5

    elif capital < 50.0:
        if score <= 3:
            return 0.02, 5
        elif score <= 6:
            return 0.02, 6
        else:
            return 0.03, 7

    elif capital < 100.0:
        if score <= 3:
            return 0.02, 7
        elif score <= 6:
            return 0.03, 8
        else:
            return 0.04, 9

    elif capital < 250.0:
        if score <= 3:
            return 0.02, 9
        elif score <= 6:
            return 0.03, 10
        else:
            return 0.05, 12

    elif capital < 500.0:
        if score <= 3:
            return 0.03, 12
        elif score <= 6:
            return 0.04, 13
        else:
            return 0.06, 14

    elif capital < 1000.0:
        if score <= 3:
            return 0.04, 14
        elif score <= 6:
            return 0.05, 15
        else:
            return 0.08, 16

    elif capital < 2000.0:
        if score <= 3:
            return 0.05, 16
        elif score <= 6:
            return 0.07, 17
        else:
            return 0.10, 18

    elif capital < 5000.0:
        if score <= 3:
            return 0.08, 18
        elif score <= 6:
            return 0.10, 18
        else:
            return 0.15, 18

    elif capital < 10000.0:
        if score <= 3:
            return 0.10, 18
        elif score <= 6:
            return 0.15, 18
        else:
            return 0.20, 18

    else:
        if score <= 3:
            return 0.15, 18
        elif score <= 6:
            return 0.20, 18
        else:
            return 0.30, 18

# ============================================================
# ENTRY-QUALITY SCORER
# ============================================================
def calculate_entry_quality_score(
    tick_direction,
    tick_confidence,
    m5_signal,
    momentum_continuation,
    pullback_continuation,
    breakout_confirmed,
    current_spread_pips
):
    score = 0

    if tick_direction in ["BUY", "SELL"]:
        score += 2

    if abs(tick_confidence) >= 8:
        score += 2
    elif abs(tick_confidence) >= 6:
        score += 1

    if m5_signal == tick_direction:
        score += 3
    elif m5_signal in ["BUY", "SELL"]:
        score += 1
    elif m5_signal and m5_signal != tick_direction:
        score -= 2

    if momentum_continuation:
        score += 2

    if pullback_continuation:
        score += 2

    if breakout_confirmed:
        score += 2

    if current_spread_pips <= 15:
        score += 2
    elif current_spread_pips <= 20:
        score += 1

    return max(0, min(score, 10))

# ============================================================
# MICRO-MOMENTUM TRACKER
# ============================================================
class MicroMomentumTracker:
    def __init__(self, capacity=20):
        self.ticks = deque(maxlen=capacity)
        self.candle_open = None
        self.last_minute = None

    def record_tick(self, price):
        current_minute = datetime.datetime.now(datetime.timezone.utc).minute

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

    def calculate_live_atr(self):
        ticks = list(self.ticks)

        if len(ticks) < 5:
            return 0.50

        ranges = []

        for i in range(1, len(ticks)):
            ranges.append(abs(ticks[i] - ticks[i - 1]))

        average_range = sum(ranges) / len(ranges)

        return max(0.20, min(average_range * 3.0, 2.00))

# ============================================================
# M5 REVERSAL SIGNAL
# ============================================================
async def get_m5_reversal_signal(account, connection, symbol):
    try:
        candles = await account.get_historical_candles(
            symbol=symbol,
            timeframe="5m",
            start_time=datetime.datetime.now(datetime.timezone.utc),
            limit=25
        )

        if not candles:
            return None

        highs = []
        lows = []
        opens = []
        closes = []

        for candle in candles:
            highs.append(float(candle.get("high", 0) or 0))
            lows.append(float(candle.get("low", 0) or 0))
            opens.append(float(candle.get("open", 0) or 0))
            closes.append(float(candle.get("close", 0) or 0))

        if len(closes) < M5_RANGE_LOOKBACK:
            return None

        recent_highs = highs[-M5_RANGE_LOOKBACK:]
        recent_lows = lows[-M5_RANGE_LOOKBACK:]

        range_high = max(recent_highs)
        range_low = min(recent_lows)

        last_open = opens[-1]
        last_high = highs[-1]
        last_low = lows[-1]
        last_close = closes[-1]

        body = abs(last_close - last_open)
        upper_wick = last_high - max(last_open, last_close)
        lower_wick = min(last_open, last_close) - last_low

        if last_high >= range_high - M5_REJECTION_BUFFER and upper_wick > body:
            return "SELL"

        if last_low <= range_low + M5_REJECTION_BUFFER and lower_wick > body:
            return "BUY"

        return None

    except Exception as error:
        print(f"[M5 SIGNAL ERROR] {error}")
        return None

# ============================================================
# MOMENTUM / PULLBACK / BREAKOUT DETECTORS
# ============================================================
def detect_momentum_continuation(tracker, direction):
    ticks = list(tracker.ticks)

    if len(ticks) < 5:
        return False

    latest = ticks[-1]

    if direction == "BUY":
        recent_high = max(ticks[-5:-1])
        return latest > recent_high

    elif direction == "SELL":
        recent_low = min(ticks[-5:-1])
        return latest < recent_low

    return False

def detect_pullback_continuation(tracker, direction):
    ticks = list(tracker.ticks)

    if len(ticks) < 6:
        return False

    latest = ticks[-1]
    previous = ticks[-2]
    pullback_low = min(ticks[-6:-1])
    pullback_high = max(ticks[-6:-1])

    if direction == "BUY":
        return previous < latest and previous > pullback_low and latest > pullback_low

    elif direction == "SELL":
        return previous > latest and previous < pullback_high and latest < pullback_high

    return False

def detect_breakout(tracker, direction):
    ticks = list(tracker.ticks)

    if len(ticks) < 10:
        return False

    latest = ticks[-1]
    recent_high = max(ticks[:-1])
    recent_low = min(ticks[:-1])

    if direction == "BUY":
        return latest > recent_high

    elif direction == "SELL":
        return latest < recent_low

    return False

# ============================================================
# LOT-SIZE NORMALIZATION
# ============================================================
def normalize_lot_size(lot, specification):
    if not specification:
        return round(lot, 2)

    min_volume = float(specification.get("minVolume", 0.01) or 0.01)
    volume_step = float(specification.get("volumeStep", 0.01) or 0.01)
    max_volume = float(specification.get("maxVolume", 100.0) or 100.0)

    if lot < min_volume:
        lot = min_volume

    steps = round(lot / volume_step)
    lot = steps * volume_step

    if lot > max_volume:
        lot = max_volume

    return round(lot, 2)

# ============================================================
# QUALITY-BASED INDIVIDUAL TP / SL
# ============================================================
def calculate_quality_based_tp_sl(
    direction,
    entry_price,
    entry_quality_score,
    live_atr
):
    """
    Strong entry:
        Wider SL for protection
        Larger TP for bigger move

    Normal entry:
        Balanced SL and TP

    Weak entry:
        Tighter SL
        Smaller TP
    """

    if entry_quality_score >= 7:
        quality_label = "STRONG"
        stop_distance = BASE_STOP_LOSS_DISTANCE_USD * 1.25
        tp_rr = STRONG_TP_RR

    elif entry_quality_score >= 4:
        quality_label = "NORMAL"
        stop_distance = BASE_STOP_LOSS_DISTANCE_USD
        tp_rr = NORMAL_TP_RR

    else:
        quality_label = "WEAK"
        stop_distance = BASE_STOP_LOSS_DISTANCE_USD * 0.75
        tp_rr = WEAK_TP_RR

    # Adapt stop distance to live volatility
    volatility_adjustment = live_atr * 0.50

    stop_distance = stop_distance + volatility_adjustment

    stop_distance = max(
        MIN_STOP_LOSS_DISTANCE_USD,
        min(stop_distance, MAX_STOP_LOSS_DISTANCE_USD)
    )

    take_profit_distance = stop_distance * tp_rr

    if direction == "BUY":
        take_profit_price = entry_price + take_profit_distance
        stop_loss_price = entry_price - stop_distance

    else:
        take_profit_price = entry_price - take_profit_distance
        stop_loss_price = entry_price + stop_distance

    return (
        round(take_profit_price, 2),
        round(stop_loss_price, 2),
        quality_label,
        round(stop_distance, 2),
        round(take_profit_distance, 2)
    )

# ============================================================
# ORDER EXECUTION
# ============================================================
async def open_quality_ticket(
    connection,
    symbol,
    direction,
    volume,
    key,
    entry_price,
    entry_quality_score,
    live_atr,
    specification=None
):
    volume = normalize_lot_size(
        volume,
        specification
    )

    take_profit_price, stop_loss_price, quality_label, stop_distance, tp_distance = calculate_quality_based_tp_sl(
        direction,
        entry_price,
        entry_quality_score,
        live_atr
    )

    bot_signature = f"GHOST-QUALITY-{quality_label} [{key}]"

    if direction == "BUY":
        result = await connection.create_market_buy_order(
            symbol=symbol,
            volume=volume,
            stop_loss=stop_loss_price,
            take_profit=take_profit_price,
            options={"comment": bot_signature}
        )

    else:
        result = await connection.create_market_sell_order(
            symbol=symbol,
            volume=volume,
            stop_loss=stop_loss_price,
            take_profit=take_profit_price,
            options={"comment": bot_signature}
        )

    print(
        f"[QUALITY TICKET OPENED] {direction} {volume} lots | "
        f"{symbol} | Quality: {quality_label} | "
        f"TP: {take_profit_price} (+{tp_distance}) | "
        f"SL: {stop_loss_price} (-{stop_distance})"
    )

    return result

async def add_quality_ticket(
    connection,
    symbol,
    direction,
    volume,
    key,
    position_number,
    entry_price,
    entry_quality_score,
    live_atr,
    specification=None
):
    volume = normalize_lot_size(
        volume,
        specification
    )

    take_profit_price, stop_loss_price, quality_label, stop_distance, tp_distance = calculate_quality_based_tp_sl(
        direction,
        entry_price,
        entry_quality_score,
        live_atr
    )

    bot_signature = f"GHOST-QUALITY-{quality_label}-{position_number} [{key}]"

    if direction == "BUY":
        result = await connection.create_market_buy_order(
            symbol=symbol,
            volume=volume,
            stop_loss=stop_loss_price,
            take_profit=take_profit_price,
            options={"comment": bot_signature}
        )

    else:
        result = await connection.create_market_sell_order(
            symbol=symbol,
            volume=volume,
            stop_loss=stop_loss_price,
            take_profit=take_profit_price,
            options={"comment": bot_signature}
        )

    print(
        f"[QUALITY TICKET ADDED] {direction} {volume} lots | "
        f"{symbol} | Position {position_number} | Quality: {quality_label} | "
        f"TP: {take_profit_price} (+{tp_distance}) | "
        f"SL: {stop_loss_price} (-{stop_distance})"
    )

    return result

# ============================================================
# GOLD SYMBOL RESOLVER
# ============================================================
GOLD_SYMBOL_CANDIDATES = [
    "XAUUSD",
    "XAUUSDm",
    "XAUUSD.r",
    "XAUUSDc",
    "XAUUSDr",
    "XAU/USD",
    "GOLD",
    "GOLDm"
]

async def resolve_broker_gold_symbol(connection, requested_symbol):
    candidates = [requested_symbol] + GOLD_SYMBOL_CANDIDATES

    seen = set()
    filtered_candidates = []

    for symbol in candidates:
        if symbol and symbol not in seen:
            seen.add(symbol)
            filtered_candidates.append(symbol)

    available_symbols = set(await connection.get_symbols())

    for symbol in filtered_candidates:
        if symbol not in available_symbols:
            continue

        validated = await validate_gold_symbol(connection, symbol)

        if validated:
            print(f"[GOLD SYMBOL RESOLVED] Using: {validated}")
            return validated

    for symbol in available_symbols:
        symbol_upper = symbol.upper()

        if "XAUUSD" in symbol_upper or symbol_upper in ["GOLD", "GOLDM"]:
            validated = await validate_gold_symbol(connection, symbol)

            if validated:
                print(f"[GOLD SYMBOL RESOLVED] Using: {validated}")
                return validated

    await connection.subscribe_to_market_data(requested_symbol)
    print(f"[GOLD SYMBOL FALLBACK] Using requested symbol: {requested_symbol}")

    return requested_symbol

async def validate_gold_symbol(connection, symbol):
    try:
        specification = await connection.get_symbol_specification(symbol)

        if not specification:
            return None

        symbol_upper = symbol.upper()
        description = str(specification.get("description", "")).upper()

        is_gold = (
            "XAU" in symbol_upper
            or "GOLD" in symbol_upper
            or "GOLD" in description
        )

        is_tradable = specification.get("tradeMode") != "SYMBOL_TRADE_MODE_DISABLED"

        if is_gold and is_tradable:
            return symbol

        return None

    except Exception as error:
        print(f"[GOLD SYMBOL VALIDATION ERROR] {symbol}: {error}")
        return None

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
        print("[SDK COMPATIBILITY] Falling back to legacy get_accounts()...")

        try:
            accounts = await api.metatrader_account_api.get_accounts()

            if isinstance(accounts, dict):
                return accounts.get("items", [])

            return accounts or []

        except Exception as legacy_error:
            print(f"[LEGACY ACCOUNT SEARCH NOTICE] {legacy_error}")
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
            account_login = str(account_value(account, "login", "")).strip()
            account_server = str(account_value(account, "server", "")).strip()

            if account_login == login_str and (
                not server_str or account_server == server_str
            ):
                matching_accounts.append(account)

        print(
            f"[ACCOUNT SEARCH] Found {len(matching_accounts)} matching MetaApi account(s) "
            f"for login {login_str}."
        )

        for account in matching_accounts:
            state = str(account_value(account, "state", "")).upper()

            if state == "DEPLOYED":
                account_id = account_value(account, "id", "")
                print(f"[ACCOUNT BOUND] Reusing deployed MetaApi node: {account_id}")
                return account

        for account in matching_accounts:
            account_id = account_value(account, "id", "")
            state = str(account_value(account, "state", "")).upper()

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
                        "METAAPI BILLING BLOCKED: MetaApi refused to deploy this trading account. "
                        "Log in to your MetaApi dashboard and top up your balance or resolve the "
                        "account quota restriction. Then press START again."
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
                    "METAAPI BILLING BLOCKED: MetaApi refused to create/deploy a new trading account. "
                    "Log in to your MetaApi dashboard and top up your balance or resolve the account "
                    "quota restriction. Then press START again."
                )

            print(f"[DEPLOY WARNING] {error_text}")

        return new_account

    except Exception as create_error:
        error_text = str(create_error)

        if is_metaapi_quota_error(error_text):
            raise Exception(
                "METAAPI BILLING BLOCKED: MetaApi rejected account creation because your MetaApi "
                "balance/quota needs to be topped up. Log in to your MetaApi dashboard, top up or "
                "resolve the restriction, then press START again."
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

            state = str(account_value(account, "state", "")).upper()

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
                            "METAAPI BILLING BLOCKED: MetaApi refused to deploy this trading account. "
                            "Top up your MetaApi balance or resolve the quota restriction."
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

                print(f"[CORE LIVE & SYNCHRONIZED] Connected account: {login}")
                return connection

            except Exception as sync_error:
                print(
                    f"[SYNC NOTICE] Synchronization notice on attempt {attempt}: "
                    f"{sync_error}"
                )

                if attempt == MAX_CONNECTION_ATTEMPTS:
                    return connection

                await asyncio.sleep(CONNECTION_RETRY_DELAY)
                continue

        except Exception as error:
            last_error = error
            print(
                f"[CONNECTION FAILED] Attempt {attempt}/{MAX_CONNECTION_ATTEMPTS}: "
                f"{error}"
            )

            if attempt < MAX_CONNECTION_ATTEMPTS:
                await asyncio.sleep(CONNECTION_RETRY_DELAY)

    raise Exception(
        f"Failed to connect MetaApi account {login} after "
        f"{MAX_CONNECTION_ATTEMPTS} attempts: {last_error}"
    )

# ============================================================
# GHOST ADAPTIVE QUALITY INDIVIDUAL-TP ENGINE
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
        f"[GHOST ADAPTIVE QUALITY INDIVIDUAL-TP ENGINE INITIALIZED] Starting trading loop for {login}..."
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
        entry_score=0,
        entry_type="WAITING",
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
            "entry_quality_score": entry_score,
            "entry_type": entry_type,
            "symbol_price": price_obj or {},
            "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        if err:
            telemetry["error"] = err

        live_account_telemetry[str(login)] = telemetry

    update_telemetry(False, symbol)

    try:
        api = get_metaapi_client(token)
        account = await get_or_create_metaapi_account(api, login, password, server)
        connection = await connect_metaapi_account(account, login)

        active_symbol = await resolve_broker_gold_symbol(connection, symbol)

        specification = await connection.get_symbol_specification(active_symbol)

        await connection.subscribe_to_market_data(active_symbol)

        terminal_state = connection.terminal_state

        print(
            f"[GHOST ENGINE LIVE] Trading {active_symbol} | "
            f"Adaptive quality individual-TP scalping enabled"
        )

        while active_trading_nodes.get(str(login), False):
            try:
                account_info = terminal_state.account_information or {}

                equity = float(account_info.get("equity", 0) or 0)
                balance = float(account_info.get("balance", 0) or 0)
                free_margin = float(account_info.get("freeMargin", 0) or 0)
                margin_level = float(account_info.get("marginLevel", 0) or 0)

                broker_connected = getattr(terminal_state, "connected", True)
                price = terminal_state.price(active_symbol)

                if not price or not price.get("bid"):
                    await connection.subscribe_to_market_data(active_symbol)

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

                current_ask = float(price.get("ask", 0) or 0)
                current_bid = float(price.get("bid", 0) or 0)
                current_price = (current_ask + current_bid) / 2.0

                tracker.record_tick(current_price)

                live_atr = tracker.calculate_live_atr()

                positions = terminal_state.positions or []

                gold_positions = [
                    position for position in positions
                    if position.get("symbol") == active_symbol
                ]

                open_position_count = len(gold_positions)

                floating_profit = 0.0

                for position in gold_positions:
                    floating_profit += float(position.get("profit", 0) or 0)

                floating_profit = round(floating_profit, 2)

                direction, confidence = tracker.evaluate()

                current_spread_pips = round(
                    (current_ask - current_bid) / 0.1,
                    2
                )

                m5_signal = await get_m5_reversal_signal(
                    account,
                    connection,
                    active_symbol
                )

                momentum_continuation = detect_momentum_continuation(
                    tracker,
                    direction
                )

                pullback_continuation = detect_pullback_continuation(
                    tracker,
                    direction
                )

                breakout_confirmed = detect_breakout(
                    tracker,
                    direction
                )

                entry_quality_score = calculate_entry_quality_score(
                    direction,
                    confidence,
                    m5_signal,
                    momentum_continuation,
                    pullback_continuation,
                    breakout_confirmed,
                    current_spread_pips
                )

                position_lot, max_positions = calculate_dynamic_scalp_plan(
                    equity,
                    balance,
                    entry_quality_score
                )

                if entry_quality_score >= 7:
                    entry_type = "STRONG"
                elif entry_quality_score >= 4:
                    entry_type = "NORMAL"
                else:
                    entry_type = "WEAK"

                update_telemetry(
                    connected=broker_connected,
                    sym=active_symbol,
                    bal=balance,
                    eq=equity,
                    f_margin=free_margin,
                    m_level=margin_level,
                    pnl=floating_profit,
                    open_count=open_position_count,
                    price_obj={
                        "ask": current_ask,
                        "bid": current_bid
                    },
                    conf=confidence,
                    entry_score=entry_quality_score,
                    entry_type=entry_type
                )

                # ================================================
                # 1. OPEN FIRST TICKET FROM ORIGINAL TICK LOGIC
                # ================================================
                if open_position_count == 0:

                    time_since_last_close = time.time() - last_batch_close_time

                    pre_entry_conditions_pass = (
                        broker_connected
                        and current_spread_pips <= MAX_ALLOWED_SPREAD_PIPS
                        and free_margin > 0
                        and time_since_last_close >= FAST_REENTRY_COOLDOWN_SECONDS
                        and direction in ["BUY", "SELL"]
                    )

                    if pre_entry_conditions_pass:

                        print(
                            f"[ORIGINAL TICK ENTRY] {direction} | "
                            f"Confidence: {confidence} | "
                            f"Entry score: {entry_quality_score} | "
                            f"Entry type: {entry_type} | "
                            f"Lot: {position_lot} | "
                            f"Max positions: {max_positions} | "
                            f"Live ATR: {live_atr}"
                        )

                        await open_quality_ticket(
                            connection,
                            active_symbol,
                            direction,
                            position_lot,
                            key,
                            current_price,
                            entry_quality_score,
                            live_atr,
                            specification
                        )

                        last_batch_entry_price = current_price
                        last_batch_close_time = time.time()
                        last_batch_direction = direction

                        await asyncio.sleep(0.2)
                        continue

                # ================================================
                # 2. ADD ANOTHER TICKET ONLY IN PROFIT
                # ================================================
                elif open_position_count < max_positions:

                    if last_batch_direction == "BUY":
                        price_progress = current_price - last_batch_entry_price

                    elif last_batch_direction == "SELL":
                        price_progress = last_batch_entry_price - current_price

                    else:
                        price_progress = 0

                    can_add_ticket = (
                        floating_profit > 0
                        and price_progress >= ADD_POSITION_MOVE_USD
                        and current_spread_pips <= MAX_ALLOWED_SPREAD_PIPS
                        and free_margin > 0
                    )

                    if can_add_ticket:

                        await add_quality_ticket(
                            connection,
                            active_symbol,
                            last_batch_direction,
                            position_lot,
                            key,
                            open_position_count + 1,
                            current_price,
                            entry_quality_score,
                            live_atr,
                            specification
                        )

                        last_batch_entry_price = current_price

                        await asyncio.sleep(0.2)
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
        update_telemetry(False, symbol, err=error_text)

    finally:
        active_trading_nodes.pop(str(login), None)
        trading_threads.pop(str(login), None)

        if str(login) in active_connections:
            try:
                old_connection = active_connections.pop(str(login), None)

                if old_connection:
                    await old_connection.close()

            except Exception:
                pass

        if str(login) in live_account_telemetry:
            live_account_telemetry[str(login)]["connected_to_broker"] = False

        print(f"[ENGINE STOPPED] Worker terminated for: {login}")

def launch_async_worker_thread(login, password, server, symbol, key, token=None):
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
# API CONTROLLER & MATCHING ROUTES
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
        "service": "Ghost Adaptive Quality Individual-TP Gold Scalper",
        "mode": "Original Tick-Momentum Entry + Quality-Based TP/SL + Multi-Position"
    }), 200

@app.route("/health", methods=["GET"])
@app.route("/ping", methods=["GET"])
def health_ping():
    return jsonify({
        "status": "healthy",
        "service": "Ghost Adaptive Quality Gold Engine",
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
    login = request.args.get("mt5_login", "").strip()

    return jsonify(
        live_account_telemetry.get(
            login,
            {"connected_to_broker": False}
        )
    ), 200

@app.route("/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/start", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/control", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/start", methods=["GET", "POST", "OPTIONS"])
def control_dispatcher():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        data = extract_request_data(request)

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
                "message": (
                    f"License [{license_key}] Verified. Ghost Adaptive Quality "
                    f"Individual-TP Scalper active on {mt5_symbol}."
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
        f"[STARTUP] Running Ghost Adaptive Quality Individual-TP Scalper "
        f"on 0.0.0.0:{port}..."
    )
    serve(app, host="0.0.0.0", port=port, threads=8)
