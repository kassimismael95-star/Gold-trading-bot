
"""Read-only drawdown information for Gold Scalper AI.

The master trading intelligence is the sole decision authority.
This module reports account drawdown only and must not block entries,
modify positions, or close trades.
"""


def drawdown_amount(initial_equity, current_equity):
    initial_equity = float(initial_equity)
    current_equity = float(current_equity)

    return max(0.0, initial_equity - current_equity)


def drawdown_percent(initial_equity, current_equity):
    initial_equity = float(initial_equity)
    current_equity = float(current_equity)

    if initial_equity <= 0:
        return 0.0

    return max(
        0.0,
        (initial_equity - current_equity)
        / initial_equity
        * 100.0,
    )


def drawdown_snapshot(initial_equity, current_equity):
    initial_equity = float(initial_equity)
    current_equity = float(current_equity)

    return {
        "initial_equity": initial_equity,
        "current_equity": current_equity,
        "drawdown_amount": drawdown_amount(
            initial_equity,
            current_equity,
        ),
        "drawdown_percent": drawdown_percent(
            initial_equity,
            current_equity,
        ),
    }


def breaker_triggered(
    initial_equity,
    current_equity,
    limit_percent=35,
):
    """Legacy compatibility: never trigger an independent breaker.

    The master intelligence receives drawdown data and makes decisions.
    """
    return False
