
def calculate_video_dynamic_burst(equity, balance, confidence_score):
    """
    Calculate the initial lot size, maximum basket positions,
    and basket profit target using the original engine tiers.
    """
    capital = max(float(equity), float(balance))
    abs_conf = abs(float(confidence_score))

    if capital < 4:
        return 0.01, 2 if abs_conf >= 7 else 1, 0.35

    elif capital < 10:
        return 0.01, 3 if abs_conf >= 6 else 2, 0.50

    elif capital < 25:
        return 0.02, 5 if abs_conf >= 7 else 3, 1.00

    elif capital < 50:
        return 0.03, 7 if abs_conf >= 6 else 5, 2.00

    elif capital < 100:
        return 0.04, 9 if abs_conf >= 6 else 7, 4.00

    elif capital < 250:
        return 0.06, 12 if abs_conf >= 6 else 9, 8.00

    elif capital < 500:
        return 0.10, 14 if abs_conf >= 6 else 12, 15.00

    elif capital < 1000:
        return 0.20, 16 if abs_conf >= 6 else 14, 30.00

    elif capital < 2000:
        return 0.35, 18 if abs_conf >= 6 else 16, 60.00

    elif capital < 5000:
        return 0.60, 18, 120.00

    elif capital < 10000:
        return 1.00, 18, 250.00

    elif capital < 25000:
        return 2.00, 18, 600.00

    else:
        return 4.00, 18, 1500.00


def calculate_added_position_lot(
    equity,
    balance,
    confidence_score,
    position_number
):
    """
    Calculate the lot size for an additional position
    using the original engine's capital and confidence tiers.
    """
    capital = max(float(equity), float(balance))
    abs_conf = abs(float(confidence_score))

    if capital < 10:
        lot = 0.01

    elif capital < 25:
        lot = 0.02 if abs_conf >= 7 else 0.01

    elif capital < 50:
        lot = 0.03 if abs_conf >= 6 else 0.02

    elif capital < 100:
        lot = 0.04 if abs_conf >= 6 else 0.03

    elif capital < 250:
        lot = 0.06 if abs_conf >= 6 else 0.04

    elif capital < 500:
        lot = 0.10 if abs_conf >= 6 else 0.06

    elif capital < 1000:
        lot = 0.20 if abs_conf >= 6 else 0.10

    elif capital < 2000:
        lot = 0.35 if abs_conf >= 6 else 0.20

    elif capital < 5000:
        lot = 0.60 if abs_conf >= 6 else 0.35

    elif capital < 10000:
        lot = 1.00 if abs_conf >= 6 else 0.60

    elif capital < 25000:
        lot = 2.00 if abs_conf >= 6 else 1.00

    else:
        lot = 4.00 if abs_conf >= 6 else 2.00

    if capital >= 25:
        lot += ((int(position_number) - 1) // 2) * 0.01

    return round(lot, 2)
