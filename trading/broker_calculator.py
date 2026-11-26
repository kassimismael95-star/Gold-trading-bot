
"""
Gold Scalper AI
Original dynamic TP/SL calculation.

This module preserves the user's specified TP/SL formula.
It does not introduce a new strategy or additional filters.
"""


def calculate_dynamic_tp_sl(
    entry_price,
    direction,
    current_spread_pips,
    recent_move,
    confidence_score,
    position_number=1,
    base_sl=2.00,
    base_tp=2.20,
):
    """
    Calculate dynamic stop-loss and take-profit prices.

    Original behavior:
      - Base SL: $2.00
      - Base TP: $2.20
      - Spread adjustment
      - Recent-movement multiplier
      - Momentum confidence multiplier
      - Position-number adjustment
      - SL clamped to $1.50-$3.00
      - TP clamped to $1.80-$3.50
      - TP distance must not be smaller than SL distance

    Returns:
        (stop_loss_price, take_profit_price)
    """

    entry_price = float(entry_price)
    current_spread_pips = max(0.0, float(current_spread_pips))
    recent_move = abs(float(recent_move))
    confidence_score = int(confidence_score)
    position_number = max(1, int(position_number))
    base_sl = float(base_sl)
    base_tp = float(base_tp)

    direction = str(direction).upper()

    if direction not in ("BUY", "SELL"):
        raise ValueError("direction must be BUY or SELL")

    if entry_price <= 0:
        raise ValueError("entry_price must be greater than zero")

    # Original spread conversion.
    spread_usd = current_spread_pips * 0.10

    # Original recent-movement multiplier.
    if recent_move > 0.50:
        movement_multiplier = 1.30
    elif recent_move > 0.25:
        movement_multiplier = 1.15
    elif recent_move > 0.10:
        movement_multiplier = 1.05
    else:
        movement_multiplier = 1.00

    # Original confidence multiplier.
    if confidence_score >= 8:
        confidence_multiplier = 1.15
    elif confidence_score >= 6:
        confidence_multiplier = 1.08
    elif confidence_score <= 2:
        confidence_multiplier = 0.90
    else:
        confidence_multiplier = 1.00

    # Original position-number adjustment.
    position_adjustment = (position_number - 1) * 0.08

    # Original SL and TP distance calculations.
    sl_distance = (
        base_sl
        + spread_usd * 0.50
        + position_adjustment
    ) * movement_multiplier

    tp_distance = (
        base_tp
        + spread_usd * 0.30
        + position_adjustment
    ) * movement_multiplier * confidence_multiplier

    # Original distance bounds.
    sl_distance = max(1.50, min(3.00, sl_distance))
    tp_distance = max(1.80, min(3.50, tp_distance))

    # Preserve the original rule: TP distance >= SL distance.
    tp_distance = max(tp_distance, sl_distance)

    # Correct directional price placement.
    if direction == "BUY":
        stop_loss = entry_price - sl_distance
        take_profit = entry_price + tp_distance
    else:
        stop_loss = entry_price + sl_distance
        take_profit = entry_price - tp_distance

    return stop_loss, take_profit
