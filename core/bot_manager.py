from core.signal_engine import MicroMomentumTracker
from core.risk_manager import (
    calculate_video_dynamic_burst,
    calculate_added_position_lot,
    calculate_dynamic_tp_sl,
    MAX_ALLOWED_SPREAD_PIPS
)
from execution.command_queue import create_command
from execution.worker_registry import get_best_worker
from execution.order_router import route_command_to_worker
from accounts.account_registry import get_account
from database.models import get_connection


def calculate_pip_value(
    symbol,
    volume
):
    if symbol == "XAUUSD":
        return 0.10 * volume

    return 0.10 * volume


def calculate_current_spread_pips(
    bid,
    ask
):
    return abs(ask - bid) / 0.01


def get_open_positions_for_session(
    bot_session_id
):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM trade_history
        WHERE bot_session_id = %s
        AND status = 'OPEN'
        ORDER BY created_at ASC
    """, (bot_session_id,))

    positions = cursor.fetchall()

    cursor.close()
    connection.close()

    return positions


def calculate_basket_profit(
    open_positions
):
    total_profit = 0.0

    for position in open_positions:
        total_profit += position.get("profit", 0)

    return total_profit


def should_add_position(
    open_positions,
    max_positions,
    direction,
    current_direction,
    current_price,
    last_entry_price
):
    if len(open_positions) >= max_positions:
        return False

    if current_direction != direction:
        return False

    if not last_entry_price:
        return False

    price_change = current_price - last_entry_price

    if direction == "BUY":
        return price_change <= -0.20

    if direction == "SELL":
        return price_change >= 0.20

    return False


def should_close_basket(
    open_positions,
    basket_target
):
    if not open_positions:
        return False

    basket_profit = calculate_basket_profit(
        open_positions
    )

    return basket_profit >= basket_target


def create_trade_command(
    user_id,
    account_id,
    bot_session_id,
    command_type,
    symbol,
    direction,
    volume,
    stop_loss,
    take_profit
):
    return create_command(
        user_id=user_id,
        account_id=account_id,
        bot_session_id=bot_session_id,
        command_type=command_type,
        symbol=symbol,
        direction=direction,
        volume=volume,
        stop_loss=stop_loss,
        take_profit=take_profit
    )


def send_trade_command(
    user_id,
    account_id,
    bot_session_id,
    command_type,
    symbol,
    direction,
    volume,
    stop_loss,
    take_profit
):
    account = get_account(
        user_id,
        account_id
    )

    if not account:
        raise ValueError("MT5 account not found.")

    worker = get_best_worker()

    if not worker:
        raise ValueError("No online worker available.")

    command = create_trade_command(
        user_id,
        account_id,
        bot_session_id,
        command_type,
        symbol,
        direction,
        volume,
        stop_loss,
        take_profit
    )

    command_id = command["id"]

    route_command_to_worker(
        worker["worker_id"],
        command_id,
        user_id,
        account_id,
        bot_session_id,
        command_type,
        symbol,
        direction,
        volume,
        stop_loss,
        take_profit
    )

    return command


def process_bot_tick(
    user_id,
    account_id,
    bot_session_id,
    symbol,
    current_price,
    bid,
    ask,
    equity,
    balance
):
    tracker = MicroMomentumTracker()

    tracker.record_tick(current_price)

    direction, confidence_score = tracker.evaluate()

    spread_pips = calculate_current_spread_pips(
        bid,
        ask
    )

    if spread_pips > MAX_ALLOWED_SPREAD_PIPS:
        return {
            "action": "WAIT",
            "reason": "SPREAD_TOO_HIGH",
            "spread_pips": spread_pips
        }

    open_positions = get_open_positions_for_session(
        bot_session_id
    )

    first_lot, max_positions, basket_target = (
        calculate_video_dynamic_burst(
            equity,
            balance,
            confidence_score
        )
    )

    if should_close_basket(
        open_positions,
        basket_target
    ):
        return {
            "action": "CLOSE_BASKET",
            "basket_profit": calculate_basket_profit(
                open_positions
            )
        }

    if not open_positions:
        if abs(confidence_score) < 6:
            return {
                "action": "WAIT",
                "reason": "LOW_CONFIDENCE"
            }

        tp_sl = calculate_dynamic_tp_sl(
            direction,
            current_price,
            spread_pips,
            confidence_score,
            1,
            tracker.recent_movement()
        )

        command = send_trade_command(
            user_id,
            account_id,
            bot_session_id,
            "OPEN_POSITION",
            symbol,
            direction,
            first_lot,
            tp_sl["stop_loss"],
            tp_sl["take_profit"]
        )

        return {
            "action": "OPEN_FIRST_POSITION",
            "command_id": command["id"],
            "direction": direction,
            "lot": first_lot,
            "stop_loss": tp_sl["stop_loss"],
            "take_profit": tp_sl["take_profit"]
        }

    last_position = open_positions[-1]

    if should_add_position(
        open_positions,
        max_positions,
        last_position["direction"],
        direction,
        current_price,
        last_position["entry_price"]
    ):
        added_lot = calculate_added_position_lot(
            equity,
            balance,
            confidence_score,
            len(open_positions) + 1
        )

        tp_sl = calculate_dynamic_tp_sl(
            direction,
            current_price,
            spread_pips,
            confidence_score,
            len(open_positions) + 1,
            tracker.recent_movement()
        )

        command = send_trade_command(
            user_id,
            account_id,
            bot_session_id,
            "OPEN_POSITION",
            symbol,
            direction,
            added_lot,
            tp_sl["stop_loss"],
            tp_sl["take_profit"]
        )

        return {
            "action": "OPEN_ADDED_POSITION",
            "command_id": command["id"],
            "position_number": len(open_positions) + 1,
            "direction": direction,
            "lot": added_lot,
            "stop_loss": tp_sl["stop_loss"],
            "take_profit": tp_sl["take_profit"]
        }

    return {
        "action": "WAIT",
        "reason": "NO_ADDITIONAL_ENTRY"
    }
