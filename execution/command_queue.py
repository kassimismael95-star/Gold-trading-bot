import uuid
from database.models import get_connection


def create_trade_command(
    user_id,
    account_id,
    bot_session_id,
    command_type,
    symbol,
    direction=None,
    volume=None,
    stop_loss=None,
    take_profit=None
):
    command_id = str(uuid.uuid4())
    idempotency_key = f"{user_id}:{account_id}:{command_id}"

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO trade_commands (
            user_id,
            account_id,
            bot_session_id,
            command_id,
            idempotency_key,
            command_type,
            symbol,
            direction,
            volume,
            stop_loss,
            take_profit
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        RETURNING id
    """, (
        user_id,
        account_id,
        bot_session_id,
        command_id,
        idempotency_key,
        command_type,
        symbol,
        direction,
        volume,
        stop_loss,
        take_profit
    ))

    database_command_id = cursor.fetchone()["id"]

    connection.commit()
    cursor.close()
    connection.close()

    return {
        "database_id": database_command_id,
        "command_id": command_id,
        "idempotency_key": idempotency_key
    }


def get_pending_commands(worker_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM trade_commands
        WHERE command_status = 'pending'
        AND assigned_worker_id = %s
        ORDER BY created_at ASC
    """, (worker_id,))

    commands = cursor.fetchall()

    cursor.close()
    connection.close()

    return commands


def claim_command(command_id, worker_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE trade_commands
        SET
            command_status = 'claimed',
            assigned_worker_id = %s
        WHERE command_id = %s
        AND command_status = 'pending'
        RETURNING id
    """, (worker_id, command_id))

    claimed = cursor.fetchone()

    connection.commit()
    cursor.close()
    connection.close()

    return claimed is not None


def mark_command_executing(command_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE trade_commands
        SET command_status = 'executing'
        WHERE command_id = %s
        AND command_status = 'claimed'
    """, (command_id,))

    connection.commit()
    cursor.close()
    connection.close()


def mark_command_executed(command_id, result):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE trade_commands
        SET
            command_status = 'executed',
            result = %s,
            executed_at = CURRENT_TIMESTAMP
        WHERE command_id = %s
        AND command_status IN ('claimed', 'executing')
    """, (result, command_id))

    connection.commit()
    cursor.close()
    connection.close()


def mark_command_failed(command_id, result):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE trade_commands
        SET
            command_status = 'failed',
            result = %s,
            executed_at = CURRENT_TIMESTAMP
        WHERE command_id = %s
        AND command_status IN ('claimed', 'executing')
    """, (result, command_id))

    connection.commit()
    cursor.close()
    connection.close()
