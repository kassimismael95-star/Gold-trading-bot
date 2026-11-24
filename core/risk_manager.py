MAX_ALLOWED_SPREAD_PIPS = 35.0

BASE_STOP_LOSS_USD = 2.00
BASE_TAKE_PROFIT_USD = 2.20

MIN_STOP_LOSS_USD = 1.50
MAX_STOP_LOSS_USD = 3.00

MIN_TAKE_PROFIT_USD = 1.80
MAX_TAKE_PROFIT_USD = 3.50


def calculate_video_dynamic_burst(
    equity,
    balance,
    confidence_score
):
    capital = max(equity, balance)
    abs_conf = abs(confidence_score)

    if capital < 4.0:
        max_positions = 2 if abs_conf >= 7 else 1
        return 0.01, max_positions, 0.35

    elif capital < 10.0:
        max_positions = 3 if abs_conf >= 6 else 2
        return 0.01, max_positions, 0.50

    elif capital < 25.0:
        max_positions = 5 if abs_conf >= 7 else 3
        return 0.02, max_positions, 1.00

    elif capital < 50.0:
        max_positions = 7 if abs_conf >= 6 else 5
        return 0.03, max_positions, 2.00

    elif capital < 100.0:
        max_positions = 9 if abs_conf >= 6 else 7
        return 0.04, max_positions, 4.00

    elif capital < 250.0:
        max_positions = 12 if abs_conf >= 6 else 9
        return 0.06, max_positions, 8.00

    elif capital < 500.0:
        max_positions = 14 if abs_conf >= 6 else 12
        return 0.10, max_positions, 15.00

    elif capital < 1000.0:
        max_positions = 16 if abs_conf >= 6 else 14
        return 0.20, max_positions, 30.00

    elif capital < 2000.0:
        max_positions = 18 if abs_conf >= 6 else 16
        return 0.35, max_positions, 60.00

    elif capital < 5000.0:
        max_positions = 18
        return 0.60, max_positions, 120.00

    elif capital < 10000.0:
        max_positions = 18
        return 1.00, max_positions, 250.00

    elif capital < 25000.0:
        max_positions = 18
        return 2.00, max_positions, 600.00

    else:
        max_positions = 18
        return 4.00, max_positions, 1500.00


def calculate_added_position_lot(
    equity,
    balance,
    confidence_score,
    position_number
):
    capital = max(equity, balance)
    abs_conf = abs(confidence_score)

    if capital < 10:
        base_lot = 0.01

    elif capital < 25:
        base_lot = 0.02 if abs_conf >= 7 else 0.01

    elif capital < 50:
        base_lot = 0.03 if abs_conf >= 6 else 0.02

    elif capital < 100:
        base_lot = 0.04 if abs_conf >= 6 else 0.03

    elif capital < 250:
        base_lot = 0.06 if abs_conf >= 6 else 0.04

    elif capital < 500:
        base_lot = 0.10 if abs_conf >= 6 else 0.06

    elif capital < 1000:
        base_lot = 0.20 if abs_conf >= 6 else 0.10

    elif capital < 2000:
        base_lot = 0.35 if abs_conf >= 6 else 0.20

    elif capital < 5000:
        base_lot = 0.60 if abs_conf >= 6 else 0.35

    elif capital < 10000:
        base_lot = 1.00 if abs_conf >= 6 else 0.60

    elif capital < 25000:
        base_lot = 2.00 if abs_conf >= 6 else 1.00

    else:
        base_lot = 4.00 if abs_conf >= 6 else 2.00

    if capital >= 25:
        bonus = ((position_number - 1) // 2) * 0.01
        base_lot += bonus

    return round(base_lot, 2)


def calculate_dynamic_tp_sl(
    direction,
    entry_price,
    current_spread_pips,
    confidence_score,
    position_number,
    recent_price_movement
):
    spread_usd = current_spread_pips * 0.10

    movement_multiplier = 1.0

    if recent_price_movement > 0.50:
        movement_multiplier = 1.30
    elif recent_price_movement > 0.25:
        movement_multiplier = 1.15
    elif recent_price_movement > 0.10:
        movement_multiplier = 1.05

    confidence_multiplier = 1.0

    if confidence_score >= 8:
        confidence_multiplier = 1.15
    elif confidence_score >= 6:
        confidence_multiplier = 1.08
    elif confidence_score <= 2:
        confidence_multiplier = 0.90

    position_adjustment = (position_number - 1) * 0.08

    stop_loss_distance = (
        BASE_STOP_LOSS_USD
        + (spread_usd * 0.50)
        + position_adjustment
    ) * movement_multiplier

    take_profit_distance = (
        BASE_TAKE_PROFIT_USD
        + (spread_usd * 0.30)
        + position_adjustment
    ) * movement_multiplier * confidence_multiplier

    stop_loss_distance = max(
        MIN_STOP_LOSS_USD,
        min(MAX_STOP_LOSS_USD, stop_loss_distance)
    )

    take_profit_distance = max(
        MIN_TAKE_PROFIT_USD,
        min(MAX_TAKE_PROFIT_USD, take_profit_distance)
    )

    if take_profit_distance < stop_loss_distance:
        take_profit_distance = stop_loss_distance

    if direction == "BUY":
        stop_loss = entry_price - stop_loss_distance
        take_profit = entry_price + take_profit_distance

    else:
        stop_loss = entry_price + stop_loss_distance
        take_profit = entry_price - take_profit_distance

    return {
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "stop_loss_distance": round(stop_loss_distance, 2),
        "take_profit_distance": round(take_profit_distance, 2),
        "reward_risk_ratio": round(
            take_profit_distance / stop_loss_distance,
            2
        )
      )
