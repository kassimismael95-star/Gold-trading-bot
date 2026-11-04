import os
import sqlite3
import asyncio
import traceback
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, session
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
from waitress import serve

from metaapi_cloud_sdk import MetaApi

# ============================================================
# APP CONFIGURATION
# ============================================================
app = Flask(__name__)
CORS(
    app,
    supports_credentials=True,
    resources={r"/*": {"origins": "*"}}
)

app.secret_key = os.environ.get("JWT_SECRET", "")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7)
)

METAAPI_TOKEN = os.environ.get("METAAPI_TOKEN", "")
CREDENTIAL_ENCRYPTION_KEY = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "")

ALLOWED_LICENSES = {"BOSSMODE98", "BOSSMODE99"}
DB_PATH = "/tmp/bot_users.db"

active_bots = {}

if not METAAPI_TOKEN:
    print("[ERROR] METAAPI_TOKEN environment variable is missing.")

if not CREDENTIAL_ENCRYPTION_KEY:
    print("[ERROR] CREDENTIAL_ENCRYPTION_KEY environment variable is missing.")

api = MetaApi(token=METAAPI_TOKEN) if METAAPI_TOKEN else None

try:
    fernet = Fernet(CREDENTIAL_ENCRYPTION_KEY.encode())
except Exception:
    fernet = None

# ============================================================
# DATABASE
# ============================================================
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt5_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                metaapi_account_id TEXT NOT NULL,
                mt5_login TEXT NOT NULL,
                mt5_password_encrypted TEXT NOT NULL,
                mt5_server TEXT NOT NULL,
                mt5_symbol TEXT DEFAULT 'XAUUSD',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

init_db()

# ============================================================
# PASSWORD / CREDENTIAL HELPERS
# ============================================================
def encrypt_mt5_password(password):
    if not fernet:
        raise ValueError("CREDENTIAL_ENCRYPTION_KEY is missing.")

    return fernet.encrypt(password.encode()).decode()


def decrypt_mt5_password(encrypted_password):
    if not fernet:
        raise ValueError("CREDENTIAL_ENCRYPTION_KEY is missing.")

    return fernet.decrypt(encrypted_password.encode()).decode()

# ============================================================
# ASYNC HELPER
# ============================================================
def run_async(coro):
    try:
        loop = asyncio.get_event_loop()

        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()

        return loop.run_until_complete(coro)

    except RuntimeError:
        return asyncio.run(coro)

# ============================================================
# AUTH DECORATORS
# ============================================================
def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        user_id = session.get("user_id")

        if not user_id:
            return jsonify({
                "success": False,
                "status": "error",
                "message": "Please log in."
            }), 401

        return func(user_id=user_id, *args, **kwargs)

    return wrapper


def license_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        data = request.get_json(silent=True) or {}

        license_key = (
            request.args.get("license_key")
            or data.get("license_key")
            or ""
        ).strip().upper()

        if license_key not in ALLOWED_LICENSES:
            return jsonify({
                "success": False,
                "status": "error",
                "message": "Invalid license key. Use BOSSMODE98 or BOSSMODE99."
            }), 401

        return func(*args, **kwargs)

    return wrapper

# ============================================================
# METAAPI CONNECTION
# ============================================================
async def get_metaapi_connection(metaapi_account_id):
    account = await api.metatrader_account_api.get_account(
        account_id=metaapi_account_id
    )

    if account.state != "DEPLOYED":
        await account.deploy()
        await account.wait_deployed()

    connection = account.get_rpc_connection()
    await connection.connect()
    await connection.wait_synchronized()

    return connection

# ============================================================
# CORS + ERROR HANDLING
# ============================================================
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = request.headers.get(
        "Origin", "*"
    )
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = (
        "GET, POST, PUT, DELETE, OPTIONS"
    )
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization, X-Requested-With"
    )
    response.headers["Content-Type"] = "application/json"
    return response


@app.errorhandler(Exception)
def handle_error(error):
    if isinstance(error, HTTPException):
        return jsonify({
            "success": False,
            "status": "error",
            "message": error.description
        }), 200

    traceback.print_exc()

    return jsonify({
        "success": False,
        "status": "error",
        "message": str(error)
    }), 200

# ============================================================
# HEALTH ROUTES
# ============================================================
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "service": "Gold Scalper Multi-User MetaApi Backend",
        "metaapi_configured": bool(METAAPI_TOKEN),
        "encryption_configured": bool(fernet)
    })


@app.route("/health", methods=["GET"])
@app.route("/ping", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "service": "Gold Scalper Backend"
    })

# ============================================================
# USER REGISTRATION / LOGIN / LOGOUT
# ============================================================
@app.route("/api/auth/register", methods=["POST", "OPTIONS"])
def register_user():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"})

    data = request.get_json(silent=True) or {}

    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not email or "@" not in email:
        return jsonify({
            "success": False,
            "message": "A valid email is required."
        })

    if len(password) < 8:
        return jsonify({
            "success": False,
            "message": "Password must be at least 8 characters."
        })

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, generate_password_hash(password))
            )
            conn.commit()

    except sqlite3.IntegrityError:
        return jsonify({
            "success": False,
            "message": "This email is already registered."
        })

    return jsonify({
        "success": True,
        "message": "Account created successfully. Please log in."
    })


@app.route("/api/auth/login", methods=["POST", "OPTIONS"])
def login_user():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"})

    data = request.get_json(silent=True) or {}

    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE email = ?",
            (email,)
        ).fetchone()

    if not row or not check_password_hash(row[1], password):
        return jsonify({
            "success": False,
            "message": "Incorrect email or password."
        })

    session.clear()
    session["user_id"] = row[0]
    session.permanent = True

    return jsonify({
        "success": True,
        "message": "Logged in successfully.",
        "user": {
            "id": row[0],
            "email": email
        }
    })


@app.route("/api/auth/logout", methods=["POST", "OPTIONS"])
def logout_user():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"})

    session.clear()

    return jsonify({
        "success": True,
        "message": "Logged out successfully."
    })


@app.route("/api/auth/me", methods=["GET"])
@login_required
def current_user(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id, email FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

    if not row:
        return jsonify({
            "success": False,
            "message": "User not found."
        })

    return jsonify({
        "success": True,
        "user": {
            "id": row[0],
            "email": row[1]
        }
    })

# ============================================================
# SAVE PRIVATE MT5 / METAAPI ACCOUNT
# ============================================================
@app.route("/api/mt5/save", methods=["POST", "OPTIONS"])
@login_required
def save_mt5_account(user_id):
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"})

    data = request.get_json(silent=True) or {}

    metaapi_account_id = str(data.get("metaapi_account_id", "")).strip()
    mt5_login = str(data.get("mt5_login", "")).strip()
    mt5_password = str(data.get("mt5_password", ""))
    mt5_server = str(data.get("mt5_server", "")).strip()
    mt5_symbol = str(data.get("mt5_symbol", "XAUUSD")).strip()

    if not all([
        metaapi_account_id,
        mt5_login,
        mt5_password,
        mt5_server
    ]):
        return jsonify({
            "success": False,
            "message": "MetaApi account ID, MT5 login, password, and server are required."
        })

    try:
        encrypted_password = encrypt_mt5_password(mt5_password)
    except Exception as error:
        return jsonify({
            "success": False,
            "message": f"Could not encrypt MT5 password: {str(error)}"
        })

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO mt5_accounts
            (
                user_id,
                metaapi_account_id,
                mt5_login,
                mt5_password_encrypted,
                mt5_server,
                mt5_symbol
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            metaapi_account_id,
            mt5_login,
            encrypted_password,
            mt5_server,
            mt5_symbol
        ))
        conn.commit()

    return jsonify({
        "success": True,
        "message": "MT5 account saved privately."
    })

# ============================================================
# LIST ONLY LOGGED-IN USER'S ACCOUNTS
# ============================================================
@app.route("/api/mt5/accounts", methods=["GET"])
@login_required
def get_user_accounts(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("""
            SELECT
                id,
                metaapi_account_id,
                mt5_login,
                mt5_server,
                mt5_symbol,
                created_at
            FROM mt5_accounts
            WHERE user_id = ?
            ORDER BY created_at DESC
        """, (user_id,)).fetchall()

    accounts = []

    for row in rows:
        accounts.append({
            "account_record_id": row[0],
            "metaapi_account_id": row[1],
            "mt5_login": row[2],
            "mt5_server": row[3],
            "mt5_symbol": row[4],
            "created_at": row[5]
        })

    return jsonify({
        "success": True,
        "accounts": accounts
    })

# ============================================================
# DELETE USER'S OWN ACCOUNT RECORD
# ============================================================
@app.route("/api/mt5/delete/<int:account_record_id>", methods=["DELETE", "OPTIONS"])
@login_required
def delete_user_account(user_id, account_record_id):
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"})

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            DELETE FROM mt5_accounts
            WHERE id = ? AND user_id = ?
        """, (account_record_id, user_id))
        conn.commit()

        deleted = cursor.rowcount

    if deleted == 0:
        return jsonify({
            "success": False,
            "message": "Account not found or you do not have access."
        }), 403

    return jsonify({
        "success": True,
        "message": "Account deleted."
    })

# ============================================================
# PRIVATE ACCOUNT STATUS
# ============================================================
@app.route("/api/status", methods=["GET", "OPTIONS"])
@login_required
@license_required
def get_account_status(user_id):
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"})

    account_record_id = request.args.get("account_record_id")

    if not account_record_id:
        return jsonify({
            "success": False,
            "message": "Missing account_record_id."
        })

    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("""
            SELECT metaapi_account_id
            FROM mt5_accounts
            WHERE id = ? AND user_id = ?
        """, (account_record_id, user_id)).fetchone()

    if not row:
        return jsonify({
            "success": False,
            "message": "You do not have access to this trading account."
        }), 403

    metaapi_account_id = row[0]

    async def read_status():
        connection = await get_metaapi_connection(metaapi_account_id)

        account_info = await connection.get_account_information()
        positions = await connection.get_positions()

        return {
            "balance": account_info["balance"],
            "equity": account_info["equity"],
            "floating_pnl": account_info["equity"] - account_info["balance"],
            "open_positions": len(positions),
            "open_positions_count": len(positions),
            "positions": [
                {
                    "id": position["id"],
                    "symbol": position["symbol"],
                    "type": position["type"],
                    "volume": position["volume"],
                    "profit": position["profit"]
                }
                for position in positions
            ]
        }

    result = run_async(read_status())

    return jsonify({
        "success": True,
        "status": "online",
        "running": active_bots.get(metaapi_account_id, False),
        **result
    })

# ============================================================
# START / STOP PRIVATE BOT
# ============================================================
@app.route("/api/control", methods=["POST", "OPTIONS"])
@app.route("/control", methods=["POST", "OPTIONS"])
@login_required
@license_required
def control_bot(user_id):
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"})

    data = request.get_json(silent=True) or {}

    command = str(data.get("command", "START")).upper()
    account_record_id = data.get("account_record_id")

    if not account_record_id:
        return jsonify({
            "success": False,
            "message": "Missing account_record_id."
        })

    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("""
            SELECT metaapi_account_id
            FROM mt5_accounts
            WHERE id = ? AND user_id = ?
        """, (account_record_id, user_id)).fetchone()

    if not row:
        return jsonify({
            "success": False,
            "message": "You do not have access to this trading account."
        }), 403

    metaapi_account_id = row[0]

    if command == "STOP":
        active_bots[metaapi_account_id] = False

        return jsonify({
            "success": True,
            "message": "Bot stopped.",
            "running": False
        })

    active_bots[metaapi_account_id] = True

    async def verify_connection():
        connection = await get_metaapi_connection(metaapi_account_id)

        account_info = await connection.get_account_information()

        return {
            "connected": True,
            "balance": account_info["balance"],
            "equity": account_info["equity"]
        }

    result = run_async(verify_connection())

    return jsonify({
        "success": True,
        "message": "Bot started.",
        "running": True,
        **result
    })

# ============================================================
# PRIVATE ACCOUNT DETAILS
# ============================================================
@app.route("/api/account", methods=["GET", "OPTIONS"])
@login_required
@license_required
def get_account_details(user_id):
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"})

    account_record_id = request.args.get("account_record_id")

    if not account_record_id:
        return jsonify({
            "success": False,
            "message": "Missing account_record_id."
        })

    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("""
            SELECT metaapi_account_id
            FROM mt5_accounts
            WHERE id = ? AND user_id = ?
        """, (account_record_id, user_id)).fetchone()

    if not row:
        return jsonify({
            "success": False,
            "message": "You do not have access to this trading account."
        }), 403

    metaapi_account_id = row[0]

    async def read_account():
        connection = await get_metaapi_connection(metaapi_account_id)
        account_info = await connection.get_account_information()

        return {
            "login": str(account_info["login"]),
            "server": account_info["server"],
            "currency": account_info["currency"],
            "balance": account_info["balance"],
            "equity": account_info["equity"],
            "connected": True
        }

    result = run_async(read_account())

    return jsonify({
        "success": True,
        **result
    })

# ============================================================
# START SERVER
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    serve(app, host="0.0.0.0", port=port, threads=8)
