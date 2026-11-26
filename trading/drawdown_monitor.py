
"""
Gold Scalper AI — Account Drawdown Monitor

Preserves the original drawdown breaker behavior:
- Drawdown is measured from the account's initial equity.
- The default emergency threshold remains 35%.
- The breaker is an account-protection trigger, not a guaranteed loss cap.

This module does not close trades itself.
The account's execution manager must respond to the breaker by:
1. Blocking new entries.
2. Requesting closure of positions according to the account's
   emergency-protection policy.
3. Confirming broker responses.
4. Recording the event in account telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Optional


@dataclass(frozen=True)
class DrawdownStatus:
    initial_equity: float
    current_equity: float
    drawdown_amount: float
    drawdown_percent: float
    limit_percent: float
    triggered: bool


def _valid_equity(value: float, name: str) -> float:
    value = float(value)

    if not isfinite(value):
        raise ValueError(f"{name}_must_be_finite")

    if value < 0:
        raise ValueError(f"{name}_cannot_be_negative")

    return value


def drawdown_percent(
    initial_equity: float,
    current_equity: float,
) -> float:
    """
    Calculate percentage drawdown from the account's initial equity.

    This preserves the original engine's calculation.

    If initial equity is zero or negative, return 100% so that
    the account is treated as unsafe for new entries.
    """
    initial_equity = float(initial_equity)
    current_equity = _valid_equity(
        current_equity,
        "current_equity",
    )

    if not isfinite(initial_equity):
        raise ValueError("initial_equity_must_be_finite")

    if initial_equity <= 0:
        return 100.0

    loss_amount = max(
        0.0,
        initial_equity - current_equity,
    )

    return loss_amount / initial_equity * 100.0


def breaker_triggered(
    initial_equity: float,
    current_equity: float,
    limit_percent: float = 35.0,
) -> bool:
    """
    Return True when account drawdown reaches or exceeds the limit.

    The default 35% threshold is retained from the original logic.
    """
    limit_percent = float(limit_percent)

    if (
        not isfinite(limit_percent)
        or limit_percent <= 0
        or limit_percent > 100
    ):
        raise ValueError(
            "limit_percent_must_be_between_0_and_100"
        )

    return (
        drawdown_percent(
            initial_equity,
            current_equity,
        )
        >= limit_percent
    )


def get_drawdown_status(
    initial_equity: float,
    current_equity: float,
    limit_percent: float = 35.0,
) -> DrawdownStatus:
    """
    Return a detailed account drawdown status.

    Use this for telemetry, account dashboard display and risk decisions.
    """
    initial_equity = float(initial_equity)
    current_equity = _valid_equity(
        current_equity,
        "current_equity",
    )

    if not isfinite(initial_equity):
        raise ValueError("initial_equity_must_be_finite")

    if initial_equity < 0:
        raise ValueError("initial_equity_cannot_be_negative")

    limit_percent = float(limit_percent)

    if (
        not isfinite(limit_percent)
        or limit_percent <= 0
        or limit_percent > 100
    ):
        raise ValueError(
            "limit_percent_must_be_between_0_and_100"
        )

    percentage = drawdown_percent(
        initial_equity,
        current_equity,
    )

    drawdown_amount = max(
        0.0,
        initial_equity - current_equity,
    )

    return DrawdownStatus(
        initial_equity=initial_equity,
        current_equity=current_equity,
        drawdown_amount=drawdown_amount,
        drawdown_percent=percentage,
        limit_percent=limit_percent,
        triggered=percentage >= limit_percent,
    )
