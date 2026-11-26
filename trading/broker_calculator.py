
"""
Gold Scalper AI - Original Dynamic TP/SL Calculator

Calculates the initial stop-loss and take-profit for each position.

The Master Live Market Controller will manage and adjust these
levels independently after the broker confirms the position.
"""

BASE_STOP_LOSS_USD = 2.00
BASE_TAKE_PROFIT_USD = 2.20

MIN_STOP_LOSS_USD = 1.50
MAX_STOP_LOSS_USD = 3.00

MIN_TAKE_PROFIT_USD = 1.80
MAX_TAKE_PROFIT_USD = 3.50


def calculate_dynamic_tp_sl(
    direction,
    entry_price,
    current_spread_pips,
    confidence_score,
    position_number,
    recent_price_movement
):
    """
    Original Gold Scalper AI dynamic TP/SL formula.

    Returns a dictionary containing:
        stop_loss
        take_profit
        stop_loss_distance
        take_profit_distance
        reward_risk_ratio
    """

    entry_price = float(entry_price)
    current_spread_pips = float(current_spread_pips)
    confidence_score = float(confidence_score)
    position_number = int(position_number)
    recent_price_movement = float(recent_price_movement)

    # Original spread conversion
    spread_usd = current_spread_pips * 0.10

    # Original market movement multiplier
    if recent_price_movement > 0.50:
        movement_multiplier = 1.30
    elif recent_price_movement > 0.25:
        movement_multiplier = 1.15
    elif recent_price_movement > 0.10:
        movement_multiplier = 1.05
    else:
        movement_multiplier = 1.00

    # Original confidence multiplier
    if confidence_score >= 8:
        confidence_multiplier = 1.15
    elif confidence_score >= 6:
        confidence_multiplier = 1.08
    elif confidence_score <= 2:
        confidence_multiplier = 0.90
    else:
        confidence_multiplier = 1.00

    # Original position-number adjustment
    position_adjustment = (position_number - 1) * 0.08

    # Original stop-loss calculation
    stop_loss_distance = (
        BASE_STOP_LOSS_USD
        + spread_usd * 0.50
        + position_adjustment
    ) * movement_multiplier

    # Original take-profit calculation
    take_profit_distance = (
        BASE_TAKE_PROFIT_USD
        + spread_usd * 0.30
        + position_adjustment
    ) * movement_multiplier * confidence_multiplier

    # Original distance boundaries
    stop_loss_distance = max(
        MIN_STOP_LOSS_USD,
        min(MAX_STOP_LOSS_USD, stop_loss_distance)
    )

    take_profit_distance = max(
        MIN_TAKE_PROFIT_USD,
        min(MAX_TAKE_PROFIT_USD, take_profit_distance)
    )

    # Original TP must be at least as far as SL
    take_profit_distance = max(
        take_profit_distance,
        stop_loss_distance
    )

    # Calculate price levels independently by direction
    if direction.upper() == "BUY":
        stop_loss = entry_price - stop_loss_distance
        take_profit = entry_price + take_profit_distance

    elif direction.upper() == "SELL":
        stop_loss = entry_price + stop_loss_distance
        take_profit = entry_price - take_profit_distance

    else:
        raise ValueError(
            f"Unsupported trading direction: {direction}"
        )

    # Preserve original dictionary interface
    return {
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "stop_loss_distance": round(stop_loss_distance, 2),
        "take_profit_distance": round(take_profit_distance, 2),
        "reward_risk_ratio": round(
            take_profit_distance / stop_loss_distance,
            2
        )
    }
