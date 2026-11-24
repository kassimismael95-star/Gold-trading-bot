
from database.models import get_connection
from accounts.credential_vault import encrypt_password


def create_mt5_account(
    user_id,
    mt5_login,
    mt5_password,
    mt5_server,
    mt5_symbol
):
    connection = get_connection()
    cursor = connection.cursor()

    encrypted_password = encrypt_password(mt5_password)

    cursor.execute("""
        INSERT INTO mt5_accounts (
            user_id,
            mt5_login,
            mt5_server,
            mt5_symbol,
            encrypted_password
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """, (
        user_id,
        mt5_login,
        mt5_server,
        mt5_symbol,
        encrypted_password
    ))

    account_id = cursor.fetchone()["id"]

    connection.commit()
    cursor.close()
    connection.close()

    return account_id


def get_user_accounts(user_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            mt5_login,
            mt5_server,
            mt5_symbol,
            account_status
        FROM mt5_accounts
        WHERE user_id = %s
        ORDER BY id DESC
    """, (user_id,))

    accounts = cursor.fetchall()

    cursor.close()
    connection.close()

    return accounts


def get_account_by_id(account_id, user_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            user_id,
            mt5_login,
            mt5_server,
            mt5_symbol,
            encrypted_password,
            account_status
        FROM mt5_accounts
        WHERE id = %s
        AND user_id = %s
    """, (account_id, user_id))

    account = cursor.fetchone()

    cursor.close()
    connection.close()

    return account


def update_account_status(account_id, status):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE mt5_accounts
        SET
            account_status = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (status, account_id))

    connection.commit()
    cursor.close()
    connection.close()
