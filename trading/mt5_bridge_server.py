
"""
GOLD SCALPER AI
File: trading/mt5_bridge_server.py

Oracle-side HTTP bridge between:
    1. Python trading controller
    2. MT5 GoldMasterEA.mq5

Responsibilities:
    - Authenticated command submission
    - Account-isolated command queue
    - MT5 command polling and acknowledgement
    - Command-result storage
    - Broker account / position / price snapshots
    - Persistent SQLite storage
    - Safe command claiming and lease recovery

IMPORTANT:
    The MT5 EA must publish broker snapshots through POST /state.
    Until it does, /positions, /account and /price return 503.
"""

import os
import json
import time
import uuid
import hmac
import sqlite3
import logging

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# ============================================================
# CONFIGURATION
# ============================================================

HOST = os.getenv("MT5_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.getenv("MT5_BRIDGE_PORT", "8080"))

API_KEY = os.getenv("MT5_BRIDGE_API_KEY", "").strip()

DATABASE_PATH = Path(
    os.getenv("MT5_BRIDGE_DB", "data/mt5_bridge.db")
)

# Technical command-delivery lease.
# This is not a trading cooldown or trading restriction.
COMMAND_LEASE_SECONDS = int(
    os.getenv("MT5_COMMAND_LEASE_SECONDS", "60")
)

MAX_REQUEST_BYTES = int(
    os.getenv("MT5_BRIDGE_MAX_REQUEST_BYTES", str(2 * 1024 * 1024))
)

LOG_LEVEL = os.getenv("MT5_BRIDGE_LOG_LEVEL", "INFO").upper()


logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s"
)

logger = logging.getLogger("gold_mt5_bridge")


# ============================================================
# STARTUP VALIDATION
# ============================================================

if not API_KEY:
    raise RuntimeError(
        "MT5_BRIDGE_API_KEY is required. "
        "Set a strong private key before starting the bridge."
    )

if len(API_KEY) < 24:
    raise RuntimeError(
        "MT5_BRIDGE_API_KEY must contain at least 24 characters."
    )

DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)


# ============================================================
# DATABASE
# ============================================================

def get_connection():
    connection = sqlite3.connect(
        str(DATABASE_PATH),
        timeout=30,
        isolation_level=None
    )

    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")

    return connection


def initialize_database():
    with get_connection() as db:

        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS bridge_commands (
                command_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                command_json TEXT NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT,
                error TEXT,
                created_at REAL NOT NULL,
                claimed_at REAL,
                completed_at REAL
            );

            CREATE INDEX IF NOT EXISTS idx_bridge_commands_queue
            ON bridge_commands(account_id, status, created_at);

            CREATE TABLE IF NOT EXISTS bridge_account_state (
                account_id TEXT PRIMARY KEY,
                account_json TEXT NOT NULL,
                positions_json TEXT NOT NULL,
                prices_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bridge_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_bridge_events_account
            ON bridge_events(account_id, created_at);
            """
        )

    logger.info("Bridge database initialized: %s", DATABASE_PATH)


# ============================================================
# COMMON HELPERS
# ============================================================

def utc_timestamp():
    return datetime.now(timezone.utc).isoformat()


def json_response(handler, status_code, payload):
    body = json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=False
    ).encode("utf-8")

    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()

    handler.wfile.write(body)


def read_json_body(handler):
    raw_length = handler.headers.get("Content-Length", "0")

    try:
        length = int(raw_length)
    except (TypeError, ValueError):
        raise ValueError("Invalid Content-Length")

    if length < 0 or length > MAX_REQUEST_BYTES:
        raise ValueError("Request body is too large or invalid")

    raw = handler.rfile.read(length)

    if not raw:
        return {}

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Request body must contain valid JSON")

    if not isinstance(payload, dict):
        raise ValueError("JSON request body must be an object")

    return payload


def valid_identifier(value):
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value.strip()) <= 256
    )


def get_query_value(query, name):
    values = query.get(name, [])

    if not values:
        return None

    value = values[0]

    if not isinstance(value, str):
        return None

    return value.strip()


def parse_json_or_default(value, default):
    if value is None:
        return default

    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


# ============================================================
# COMMAND QUEUE
# ============================================================

def submit_command(account_id, command):
    if not valid_identifier(account_id):
        raise ValueError("A valid account_id is required")

    if not isinstance(command, dict):
        raise ValueError("command must be a JSON object")

    command_id = str(uuid.uuid4())
    now = time.time()

    command_record = dict(command)

    # Ensure the account identifier is carried with the command.
    command_record["account_id"] = account_id

    with get_connection() as db:
        db.execute(
            """
            INSERT INTO bridge_commands (
                command_id,
                account_id,
                command_json,
                status,
                created_at
            )
            VALUES (?, ?, ?, 'queued', ?)
            """,
            (
                command_id,
                account_id,
                json.dumps(
                    command_record,
                    separators=(",", ":"),
                    ensure_ascii=False
                ),
                now
            )
        )

    logger.info(
        "Command queued: id=%s account=%s type=%s",
        command_id,
        account_id,
        command_record.get("action", command_record.get("type", "unknown"))
    )

    return command_id


def claim_next_command(account_id):
    """
    Atomically claim one queued command for this account.

    Expired processing leases are returned to the queue. A command
    whose result is already recorded is never queued again.
    """

    now = time.time()
    expired_before = now - COMMAND_LEASE_SECONDS

    with get_connection() as db:

        db.execute("BEGIN IMMEDIATE")

        try:
            # Recover commands whose EA claim lease expired.
            db.execute(
                """
                UPDATE bridge_commands
                SET status = 'queued',
                    claimed_at = NULL
                WHERE account_id = ?
                  AND status = 'processing'
                  AND claimed_at IS NOT NULL
                  AND claimed_at < ?
                """,
                (account_id, expired_before)
            )

            row = db.execute(
                """
                SELECT command_id, command_json
                FROM bridge_commands
                WHERE account_id = ?
                  AND status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (account_id,)
            ).fetchone()

            if row is None:
                db.execute("COMMIT")
                return None

            command_id = row["command_id"]

            updated = db.execute(
                """
                UPDATE bridge_commands
                SET status = 'processing',
                    claimed_at = ?
                WHERE command_id = ?
                  AND account_id = ?
                  AND status = 'queued'
                """,
                (now, command_id, account_id)
            )

            if updated.rowcount != 1:
                db.execute("ROLLBACK")
                return None

            db.execute("COMMIT")

            command = parse_json_or_default(
                row["command_json"],
                {}
            )

            return {
                "command_id": command_id,
                "command": command
            }

        except Exception:
            db.execute("ROLLBACK")
            raise


def record_command_result(command_id, payload):
    if not valid_identifier(command_id):
        raise ValueError("Invalid command_id")

    if not isinstance(payload, dict):
        raise ValueError("Result must be a JSON object")

    success = payload.get("success")

    if not isinstance(success, bool):
        raise ValueError(
            "Command result must include boolean success"
        )

    result_json = json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=False
    )

    now = time.time()

    if success:
        status = "complete"
        error = None
    else:
        status = "failed"
        error = str(
            payload.get("error")
            or payload.get("message")
            or "MT5 command failed"
        )

    with get_connection() as db:

        db.execute("BEGIN IMMEDIATE")

        try:
            row = db.execute(
                """
                SELECT status
                FROM bridge_commands
                WHERE command_id = ?
                """,
                (command_id,)
            ).fetchone()

            if row is None:
                db.execute("ROLLBACK")
                return False

            # Never overwrite an already completed result.
            if row["status"] in (
                "complete",
                "failed",
                "rejected",
                "cancelled"
            ):
                db.execute("COMMIT")
                return True

            db.execute(
                """
                UPDATE bridge_commands
                SET status = ?,
                    result_json = ?,
                    error = ?,
                    completed_at = ?
                WHERE command_id = ?
                """,
                (
                    status,
                    result_json,
                    error,
                    now,
                    command_id
                )
            )

            db.execute("COMMIT")

        except Exception:
            db.execute("ROLLBACK")
            raise

    logger.info(
        "Command result recorded: id=%s status=%s",
        command_id,
        status
    )

    return True


def get_command(command_id):
    with get_connection() as db:
        row = db.execute(
            """
            SELECT
                command_id,
                account_id,
                status,
                result_json,
                error,
                created_at,
                completed_at
            FROM bridge_commands
            WHERE command_id = ?
            """,
            (command_id,)
        ).fetchone()

    if row is None:
        return None

    result = parse_json_or_default(
        row["result_json"],
        None
    )

    return {
        "command_id": row["command_id"],
        "account_id": row["account_id"],
        "status": row["status"],
        "success": (
            result.get("success")
            if isinstance(result, dict)
            else None
        ),
        "result": result,
        "error": row["error"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"]
    }


# ============================================================
# BROKER STATE STORAGE
# ============================================================

def save_account_state(account_id, payload):
    if not valid_identifier(account_id):
        raise ValueError("A valid account_id is required")

    account = payload.get("account", {})
    positions = payload.get("positions", [])
    prices = payload.get("prices", {})

    if not isinstance(account, dict):
        raise ValueError("account must be an object")

    if not isinstance(positions, list):
        raise ValueError("positions must be an array")

    if not isinstance(prices, dict):
        raise ValueError("prices must be an object")

    now = time.time()

    account_json = json.dumps(
        account,
        separators=(",", ":"),
        ensure_ascii=False
    )

    positions_json = json.dumps(
        positions,
        separators=(",", ":"),
        ensure_ascii=False
    )

    prices_json = json.dumps(
        prices,
        separators=(",", ":"),
        ensure_ascii=False
    )

    with get_connection() as db:
        db.execute(
            """
            INSERT INTO bridge_account_state (
                account_id,
                account_json,
                positions_json,
                prices_json,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(account_id)
            DO UPDATE SET
                account_json = excluded.account_json,
                positions_json = excluded.positions_json,
                prices_json = excluded.prices_json,
                updated_at = excluded.updated_at
            """,
            (
                account_id,
                account_json,
                positions_json,
                prices_json,
                now
            )
        )

    return {
        "account_id": account_id,
        "updated_at": now
    }


def get_account_state(account_id):
    if not valid_identifier(account_id):
        return None

    with get_connection() as db:
        row = db.execute(
            """
            SELECT
                account_json,
                positions_json,
                prices_json,
                updated_at
            FROM bridge_account_state
            WHERE account_id = ?
            """,
            (account_id,)
        ).fetchone()

    if row is None:
        return None

    return {
        "account": parse_json_or_default(
            row["account_json"],
            {}
        ),
        "positions": parse_json_or_default(
            row["positions_json"],
            []
        ),
        "prices": parse_json_or_default(
            row["prices_json"],
            {}
        ),
        "updated_at": row["updated_at"]
    }


# ============================================================
# HTTP HANDLER
# ============================================================

class MT5BridgeHandler(BaseHTTPRequestHandler):

    server_version = "GoldScalperBridge/1.0"

    def log_message(self, format_string, *args):
        logger.info(
            "%s - %s",
            self.address_string(),
            format_string % args
        )

    def authenticate(self):
        authorization = self.headers.get(
            "Authorization",
            ""
        )

        expected = "Bearer " + API_KEY

        return hmac.compare_digest(
            authorization.strip(),
            expected
        )

    def require_authentication(self):
        if self.authenticate():
            return True

        json_response(
            self,
            401,
            {
                "success": False,
                "error": "Unauthorized"
            }
        )

        return False

    def do_GET(self):

        if not self.require_authentication():
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        try:

            # ------------------------------------------------
            # HEALTH
            # ------------------------------------------------

            if path == "/health":
                json_response(
                    self,
                    200,
                    {
                        "success": True,
                        "status": "ok",
                        "service": "gold-mt5-bridge",
                        "time": utc_timestamp()
                    }
                )
                return

            # ------------------------------------------------
            # MT5 COMMAND POLLING
            # ------------------------------------------------

            if path == "/commands/next":

                account_id = get_query_value(
                    query,
                    "account_id"
                )

                if not valid_identifier(account_id):
                    json_response(
                        self,
                        400,
                        {
                            "success": False,
                            "error": "account_id is required"
                        }
                    )
                    return

                command = claim_next_command(account_id)

                if command is None:
                    json_response(
                        self,
                        200,
                        {
                            "command_id": None,
                            "command": None
                        }
                    )
                    return

                json_response(
                    self,
                    200,
                    command
                )
                return

            # ------------------------------------------------
            # COMMAND RESULT POLLING
            # ------------------------------------------------

            if path.startswith("/commands/"):

                command_id = unquote(
                    path.split("/", 2)[2]
                )

                if command_id.endswith("/result"):
                    json_response(
                        self,
                        404,
                        {
                            "success": False,
                            "error": "Use POST to submit command results"
                        }
                    )
                    return

                result = get_command(command_id)

                if result is None:
                    json_response(
                        self,
                        404,
                        {
                            "success": False,
                            "error": "Command not found"
                        }
                    )
                    return

                json_response(
                    self,
                    200,
                    result
                )
                return

            # ------------------------------------------------
            # BROKER POSITIONS
            # ------------------------------------------------

            if path == "/positions":

                account_id = get_query_value(
                    query,
                    "account_id"
                )

                state = get_account_state(account_id)

                if state is None:
                    json_response(
                        self,
                        503,
                        {
                            "success": False,
                            "error": "No MT5 position snapshot received yet"
                        }
                    )
                    return

                json_response(
                    self,
                    200,
                    {
                        "success": True,
                        "account_id": account_id,
                        "positions": state["positions"],
                        "updated_at": state["updated_at"]
                    }
                )
                return

            # ------------------------------------------------
            # ACCOUNT INFORMATION
            # ------------------------------------------------

            if path == "/account":

                account_id = get_query_value(
                    query,
                    "account_id"
                )

                state = get_account_state(account_id)

                if state is None:
                    json_response(
                        self,
                        503,
                        {
                            "success": False,
                            "error": "No MT5 account snapshot received yet"
                        }
                    )
                    return

                json_response(
                    self,
                    200,
                    {
                        "success": True,
                        "account_id": account_id,
                        "account": state["account"],
                        "updated_at": state["updated_at"]
                    }
                )
                return

            # ------------------------------------------------
            # SYMBOL PRICE
            # ------------------------------------------------

            if path == "/price":

                account_id = get_query_value(
                    query,
                    "account_id"
                )

                symbol = get_query_value(
                    query,
                    "symbol"
                )

                if not symbol:
                    json_response(
                        self,
                        400,
                        {
                            "success": False,
                            "error": "symbol is required"
                        }
                    )
                    return

                state = get_account_state(account_id)

                if state is None:
                    json_response(
                        self,
                        503,
                        {
                            "success": False,
                            "error": "No MT5 price snapshot received yet"
                        }
                    )
                    return

                price = state["prices"].get(symbol)

                if price is None:
                    json_response(
                        self,
                        404,
                        {
                            "success": False,
                            "error": "Symbol price not available",
                            "symbol": symbol
                        }
                    )
                    return

                json_response(
                    self,
                    200,
                    {
                        "success": True,
                        "account_id": account_id,
                        "symbol": symbol,
                        "price": price,
                        "updated_at": state["updated_at"]
                    }
                )
                return

            json_response(
                self,
                404,
                {
                    "success": False,
                    "error": "Endpoint not found"
                }
            )

        except Exception as exc:
            logger.exception("GET request failed")

            json_response(
                self,
                500,
                {
                    "success": False,
                    "error": str(exc)
                }
            )

    def do_POST(self):

        if not self.require_authentication():
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        try:
            payload = read_json_body(self)

            # ------------------------------------------------
            # SUBMIT COMMAND FROM PYTHON CONTROLLER
            # ------------------------------------------------

            if path == "/commands":

                account_id = payload.get("account_id")
                command = payload.get("command")

                command_id = submit_command(
                    account_id,
                    command
                )

                json_response(
                    self,
                    202,
                    {
                        "success": True,
                        "command_id": command_id,
                        "status": "queued"
                    }
                )
                return

            # ------------------------------------------------
            # MT5 EA REPORTS COMMAND RESULT
            # ------------------------------------------------

            if path.startswith("/commands/") and path.endswith("/result"):

                parts = path.strip("/").split("/")

                if len(parts) != 3:
                    json_response(
                        self,
                        400,
                        {
                            "success": False,
                            "error": "Invalid command result route"
                        }
                    )
                    return

                command_id = unquote(parts[1])

                recorded = record_command_result(
                    command_id,
                    payload
                )

                if not recorded:
                    json_response(
                        self,
                        404,
                        {
                            "success": False,
                            "error": "Command not found"
                        }
                    )
                    return

                json_response(
                    self,
                    200,
                    {
                        "success": True,
                        "command_id": command_id,
                        "status": "recorded"
                    }
                )
                return

            # ------------------------------------------------
            # MT5 EA PUBLISHES BROKER STATE
            # ------------------------------------------------

            if path == "/state":

                account_id = payload.get("account_id")

                result = save_account_state(
                    account_id,
                    payload
                )

                json_response(
                    self,
                    200,
                    {
                        "success": True,
                        **result
                    }
                )
                return

            json_response(
                self,
                404,
                {
                    "success": False,
                    "error": "Endpoint not found"
                }
            )

        except ValueError as exc:
            json_response(
                self,
                400,
                {
                    "success": False,
                    "error": str(exc)
                }
            )

        except Exception as exc:
            logger.exception("POST request failed")

            json_response(
                self,
                500,
                {
                    "success": False,
                    "error": str(exc)
                }
            )


# ============================================================
# SERVER
# ============================================================

class MT5BridgeServer(ThreadingHTTPServer):

    allow_reuse_address = True
    daemon_threads = True


def main():

    initialize_database()

    server = MT5BridgeServer(
        (HOST, PORT),
        MT5BridgeHandler
    )

    logger.info(
        "Gold Scalper MT5 bridge listening on %s:%s",
        HOST,
        PORT
    )

    logger.info(
        "SQLite database: %s",
        DATABASE_PATH.resolve()
    )

    try:
        server.serve_forever(
            poll_interval=0.25
        )

    except KeyboardInterrupt:
        logger.info("Bridge shutdown requested")

    finally:
        server.shutdown()
        server.server_close()
        logger.info("Bridge stopped")


if __name__ == "__main__":
    main()
