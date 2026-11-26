
"""
Gold Scalper AI
Original account-tier lot and burst calculator.

Preserves the user's specified capital tiers, confidence
conditions, burst targets, and added-position lot sizing.
"""


def calculate_video_dynamic_burst(
    equity,
    balance,
    confidence_score,
):
    """
    Calculate the original burst settings.

    Returns:
        (lot_size, max_positions, target_profit_usd)
    """

    equity = float(equity)
    balance = float(balance)
    confidence = abs(int(confidence_score))

    # Use current positive equity as the active capital value.
    # Fall back to balance if equity is unavailable or non-positive.
    capital = equity if equity > 0 else balance

    if capital <= 0:
        return 0.01, 1, 0.35

    if capital < 4:
        lot = 0.01
        positions = 2 if confidence >= 7 else 1
        target = 0.35

    elif capital < 10:
        lot = 0.01
        positions = 3 if confidence >= 6 else 2
        target = 0.50

    elif capital < 25:
        lot = 0.02
        positions = 5 if confidence >= 7 else 3
        target = 1.00

    elif capital < 50:
        lot = 0.03
        positions = 7 if confidence >= 6 else 5
        target = 2.00

    elif capital < 100:
        lot = 0.04
        positions = 9 if confidence >= 6 else 7
        target = 4.00

    elif capital < 250:
        lot = 0.06
        positions = 12 if confidence >= 6 else 9
        target = 8.00

    elif capital < 500:
        lot = 0.10
        positions = 14 if confidence >= 6 else 12
        target = 15.00

    elif capital < 1000:
        lot = 0.20
        positions = 16 if confidence >= 6 else 14
        target = 30.00

    elif capital < 2000:
        lot = 0.35
        positions = 18 if confidence >= 6 else 16
        target = 60.00

    elif capital < 5000:
        lot = 0.60
        positions = 18
        target = 120.00

    elif capital < 10000:
        lot = 1.00
        positions = 18
        target = 250.00

    elif capital < 25000:
        lot = 2.00
        positions = 18
        target = 600.00

    else:
        lot = 4.00
        positions = 18
        target = 1500.00

    return lot, positions, target


def calculate_added_position_lot(
    capital,
    confidence_score,
    position_number,
):
    """
    Calculate the original lot size for an added position.

    Preserves the original account tiers, confidence rules,
    and capital-based position-number bonus.
    """

    capital = float(capital)
    confidence = abs(int(confidence_score))
    position_number = max(1, int(position_number))

    if capital <= 0:
        return 0.01

    if capital < 10:
        lot = 0.01

    elif capital < 25:
        lot = 0.02 if confidence >= 7 else 0.01

    elif capital < 50:
        lot = 0.03 if confidence >= 6 else 0.02

    elif capital < 100:
        lot = 0.04 if confidence >= 6 else 0.03

    elif capital < 250:
        lot = 0.06 if confidence >= 6 else 0.04

    elif capital < 500:
        lot = 0.10 if confidence >= 6 else 0.06

    elif capital < 1000:
        lot = 0.20 if confidence >= 6 else 0.10

    elif capital < 2000:
        lot = 0.35 if confidence >= 6 else 0.20

    elif capital < 5000:
        lot = 0.60 if confidence >= 6 else 0.35

    elif capital < 10000:
        lot = 1.00 if confidence >= 6 else 0.60

    elif capital < 25000:
        lot = 2.00 if confidence >= 6 else 1.00

    else:
        lot = 4.00 if confidence >= 6 else 2.00

    # Original bonus for capital >= $25.
    if capital >= 25:
        bonus = ((position_number - 1) // 2) * 0.01
        lot += bonus

    return round(lot, 2)
