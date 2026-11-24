"""
Database migrations.

Run this once after database/models.py has initialized the core tables.
"""

from database.models import get_connection


def create_user_sessions_table():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_token TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id
        ON user_sessions (user_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at
        ON user_sessions (expires_at)
    """)

    connection.commit()
    cursor.close()
    connection.close()


def create_command_queue_indexes():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_trade_commands_status_created
        ON trade_commands (status, created_at)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_trade_commands_session
        ON trade_commands (bot_session_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_trade_commands_account
        ON trade_commands (account_id)
    """)

    connection.commit()
    cursor.close()
    connection.close()


def create_worker_registry_indexes():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_worker_registry_status_load
        ON worker_registry (worker_status, current_load)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_worker_registry_last_heartbeat
        ON worker_registry (last_heartbeat)
    """)

    connection.commit()
    cursor.close()
    connection.close()


def create_trade_history_indexes():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_trade_history_session_status
        ON trade_history (bot_session_id, status)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_trade_history_user_created
        ON trade_history (user_id, created_at)
    """)

    connection.commit()
    cursor.close()
    connection.close()


def run_migrations():
    create_user_sessions_table()
    create_command_queue_indexes()
    create_worker_registry_indexes()
    create_trade_history_indexes()


if __name__ == "__main__":
    run_migrations()
