"""
Session helpers.

A session proves that a browser is signed in. It does not prove
license entitlement, ownership of an MT5 account, or permission
to execute a trade.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone

from database.models import get_connection


SESSION_LIFETIME_DAYS = 30


def get_secret_key():
    secret_key = os.environ.get("SECRET_KEY")

    if not secret_key:
        raise RuntimeError("SECRET_KEY is required.")

    return secret_key


def create_session(user_id):
    session_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=SESSION_LIFETIME_DAYS
    )

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO user_sessions (
            user_id,
            session_token,
            expires_at
        )
        VALUES (
            %s, %s, %s
        )
        RETURNING id
    """, (
        user_id,
        session_token,
        expires_at
    ))

    session_id = cursor.fetchone()["id"]

    connection.commit()
    cursor.close()
    connection.close()

    return {
        "session_id": session_id,
        "session_token": session_token,
        "expires_at": expires_at
    }


def get_session(session_token):
    if not session_token:
        return None

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            s.id AS session_id,
            s.user_id,
            s.expires_at,
            u.email
        FROM user_sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.session_token = %s
        AND s.expires_at > %s
    """, (
        session_token,
        datetime.now(timezone.utc)
    ))

    session = cursor.fetchone()

    cursor.close()
    connection.close()

    return session


def require_authenticated_user(request):
    """
    Return the signed-in user, or raise PermissionError.

    This only verifies the browser session. It must not be treated
    as license or trading authorization.
    """
    session_token = request.cookies.get("session_token")

    session = get_session(session_token)

    if not session:
        raise PermissionError("Authentication required.")

    return session


def sign_out(session_token):
    if not session_token:
        return False

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM user_sessions
        WHERE session_token = %s
    """, (session_token,))

    deleted = cursor.rowcount > 0

    connection.commit()
    cursor.close()
    connection.close()

    return deleted
