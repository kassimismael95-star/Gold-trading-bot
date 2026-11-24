from database.models import get_connection


def create_reconciliation_record(
    user_id,
    account_id,
    bot_session_id,
    reconciliation_type,
    details
):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO trade_history (
            user_id,
            account_id,
            bot_session_id,
            symbol,
            status,
            profit
        )
        VALUES (
            %s, %s, %s, %s, %s, %s
        )
        RETURNING id
    """, (
        user_id,
        account_id,
        bot_session_id,
        details.get("symbol", "UNKNOWN"),
        reconciliation_type,
        details.get("profit", 0)
    ))

    record_id = cursor.fetchone()["id"]

    connection.commit()
    cursor.close()
    connection.close()

    return record_id


def compare_positions(database_positions, broker_positions):
    database_tickets = {
        position["ticket"]
        for position in database_positions
        if position.get("ticket")
    }

    broker_tickets = {
        position["ticket"]
        for position in broker_positions
        if position.get("ticket")
    }

    missing_in_database = list(
        broker_tickets - database_tickets
    )

    missing_in_broker = list(
        database_tickets - broker_tickets
    )

    return {
        "missing_in_database": missing_in_database,
        "missing_in_broker": missing_in_broker,
        "matched_tickets": list(
            database_tickets & broker_tickets
        )
    }


def is_position_safe_to_resume(
    broker_position,
    expected_direction,
    expected_symbol
):
    if not broker_position:
        return False

    broker_direction = broker_position.get("type", "")
    broker_symbol = broker_position.get("symbol", "")

    return (
        broker_direction == expected_direction
        and broker_symbol == expected_symbol
    )


def reconcile_after_reconnect(
    user_id,
    account_id,
    bot_session_id,
    database_positions,
    broker_positions
):
    result = compare_positions(
        database_positions,
        broker_positions
    )

    if result["missing_in_database"]:
        create_reconciliation_record(
            user_id,
            account_id,
            bot_session_id,
            "BROKER_POSITION_FOUND",
            {
                "symbol": "MULTIPLE",
                "profit": 0
            }
        )

    if result["missing_in_broker"]:
        create_reconciliation_record(
            user_id,
            account_id,
            bot_session_id,
            "DATABASE_POSITION_NOT_FOUND",
            {
                "symbol": "MULTIPLE",
                "profit": 0
            }
        )

    return result
