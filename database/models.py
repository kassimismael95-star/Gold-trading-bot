import os
import psycopg2
from psycopg2.extras import RealDictCursor


def get_connection():
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise ValueError("DATABASE_URL is missing.")

    return psycopg2.connect(
        database_url,
        cursor_factory=RealDictCursor
    )


def init_database():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            license_key TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mt5_accounts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            mt5_login TEXT NOT NULL,
            mt5_server TEXT NOT NULL,
            mt5_symbol TEXT NOT NULL DEFAULT 'XAUUSDm',
            encrypted_password TEXT NOT NULL,
            account_status TEXT NOT NULL DEFAULT 'disconnected',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            account_id INTEGER NOT NULL REFERENCES mt5_accounts(id),
            session_status TEXT NOT NULL DEFAULT 'stopped',
            risk_profile TEXT NOT NULL DEFAULT 'BALANCED',
            assigned_worker_id TEXT,
            started_at TIMESTAMP,
            stopped_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_commands (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            account_id INTEGER NOT NULL REFERENCES mt5_accounts(id),
            bot_session_id INTEGER NOT NULL REFERENCES bot_sessions(id),
            command_id TEXT UNIQUE NOT NULL,
            idempotency_key TEXT UNIQUE NOT NULL,
            command_type TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT,
            volume NUMERIC,
            stop_loss NUMERIC,
            take_profit NUMERIC,
            command_status TEXT NOT NULL DEFAULT 'pending',
            assigned_worker_id TEXT,
            result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            executed_at TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_history (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            account_id INTEGER NOT NULL REFERENCES mt5_accounts(id),
            bot_session_id INTEGER NOT NULL REFERENCES bot_sessions(id),
            ticket TEXT,
            symbol TEXT NOT NULL,
            direction TEXT,
            volume NUMERIC,
            entry_price NUMERIC,
            exit_price NUMERIC,
            profit NUMERIC,
            status TEXT,
            opened_at TIMESTAMP,
            closed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS worker_registry (
            id SERIAL PRIMARY KEY,
            worker_id TEXT UNIQUE NOT NULL,
            worker_status TEXT NOT NULL DEFAULT 'offline',
            max_accounts INTEGER NOT NULL DEFAULT 20,
            active_accounts INTEGER NOT NULL DEFAULT 0,
            cpu_usage NUMERIC DEFAULT 0,
            memory_usage NUMERIC DEFAULT 0,
            last_heartbeat TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.commit()
    cursor.close()
    connection.close()


def create_user(email, password_hash, license_key):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO users (
            email,
            password_hash,
            license_key
        )
        VALUES (%s, %s, %s)
        RETURNING id
    """, (
        email,
        password_hash,
        license_key
    ))

    user_id = cursor.fetchone()["id"]

    connection.commit()
    cursor.close()
    connection.close()

    return user_id


def get_user_by_email(email):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM users
        WHERE email = %s
    """, (email,))

    user = cursor.fetchone()

    cursor.close()
    connection.close()

    return user


def get_user_by_id(user_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM users
        WHERE id = %s
    """, (user_id,))

    user = cursor.fetchone()

    cursor.close()
    connection.close()

    return user
