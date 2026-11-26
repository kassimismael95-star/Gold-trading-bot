
from dataclasses import dataclass
from typing import Any, Dict, Optional


VALID_MOMENTUM_STATES = {
    "strong",
    "neutral",
    "weak",
    "reversing",
    "unknown"
}


@dataclass
class PositionAssessment:
    """
    Live assessment for one broker position.

    All prices and profit values must relate to this individual
    position, not another position or another trading account.
    """

    position_id: str
    direction: str

    current_price: float
    entry_price: float

    current_stop_loss: Optional[float]
    current_take_profit: Optional[float]

    floating_profit: float
    maximum_floating_profit: float

    momentum_state: str
    reversal_confirmed: bool

    proposed_stop_loss: Optional[float] = None
    proposed_take_profit: Optional[float] = None

    partial_close_volume: Optional[float] = None

    confidence: Optional[float] = None
    explanation: Optional[str] = None


class PositionPolicy:
    """
    Converts assessed live market conditions into position actions.

    It does not:
    - Generate new BUY or SELL entries.
    - Change the original entry engine.
    - Invent stop-loss or take-profit distances.
    - Increase risk by moving an SL backwards.
    - Close every position just because one position reverses.
    """

    def evaluate(self, assessment: PositionAssessment) -> Dict[str, Any]:
        self._validate(assessment)

        position_id = str(assessment.position_id)
        direction = assessment.direction.upper()
        momentum = assessment.momentum_state.lower()

        decision = {
            "position_id": position_id,
            "action": "hold",
            "reason": "No management change requested",
            "stop_loss": None,
            "take_profit": None,
            "partial_close_volume": None,
            "close_position": False,
            "reversal_confirmed": False,
            "management_state": momentum
        }

        # A confirmed reversal affects this position only.
        # It does not create an opposite-direction entry.
        if assessment.reversal_confirmed:
            decision.update({
                "action": "close",
                "reason": "Confirmed reversal for this position",
                "close_position": True,
                "reversal_confirmed": True
            })
            return decision

        proposed_sl = self._safe_stop_loss(
            direction,
            assessment.current_stop_loss,
            assessment.proposed_stop_loss
        )

        proposed_tp = self._valid_take_profit(
            assessment.proposed_take_profit
        )

        if proposed_sl is not None:
            decision["stop_loss"] = proposed_sl

        if proposed_tp is not None:
            decision["take_profit"] = proposed_tp

        # Strong continuation: allow the evaluator to extend
        # the target and/or protect the position with a tighter SL.
        if momentum == "strong":
            decision["reason"] = (
                "Strong continuation; preserve the position "
                "and apply valid protective adjustments"
            )

        # Weak momentum: accept only protective changes supplied
        # by the evaluator. Do not invent a profit threshold.
        elif momentum == "weak":
            decision["reason"] = (
                "Momentum weakening; apply supplied protective "
                "adjustments if available"
            )

        # Neutral conditions: leave the position open unless
        # the evaluator supplies a valid SL/TP adjustment.
        elif momentum == "neutral":
            decision["reason"] = (
                "Neutral conditions; maintain the position"
            )

        elif momentum == "reversing":
            decision["reason"] = (
                "Reversal developing but not confirmed; "
                "maintain protection and wait for confirmation"
            )

        else:
            decision["reason"] = (
                "Market assessment unavailable; retain broker "
                "protection and do not invent an exit signal"
            )

        # Partial close is permitted only when explicitly proposed
        # by the evaluator with a positive volume.
        partial_volume = assessment.partial_close_volume

        if partial_volume is not None:
            partial_volume = float(partial_volume)

            if partial_volume > 0:
                decision["partial_close_volume"] = partial_volume

                if decision["action"] == "hold":
                    decision["action"] = "partial_close"

                decision["reason"] += (
                    "; evaluator requested a partial close"
                )

        if (
            decision["stop_loss"] is not None
            or decision["take_profit"] is not None
        ):
            if decision["action"] == "hold":
                decision["action"] = "modify"

        return decision

    @staticmethod
    def _safe_stop_loss(direction, current_sl, proposed_sl):
        """
        A BUY stop may move upward, never downward.
        A SELL stop may move downward, never upward.

        A missing current SL can be set by the evaluator.
        """
        if proposed_sl is None:
            return None

        proposed_sl = float(proposed_sl)

        if proposed_sl <= 0:
            return None

        if current_sl is None:
            return proposed_sl

        current_sl = float(current_sl)

        if direction == "BUY":
            return proposed_sl if proposed_sl > current_sl else None

        if direction == "SELL":
            return proposed_sl if proposed_sl < current_sl else None

        return None

    @staticmethod
    def _valid_take_profit(proposed_tp):
        if proposed_tp is None:
            return None

        proposed_tp = float(proposed_tp)

        if proposed_tp <= 0:
            return None

        return proposed_tp

    @staticmethod
    def _validate(assessment):
        if not isinstance(assessment, PositionAssessment):
            raise TypeError(
                "assessment must be a PositionAssessment"
            )

        if not assessment.position_id:
            raise ValueError("position_id is required")

        if assessment.direction.upper() not in ("BUY", "SELL"):
            raise ValueError("direction must be BUY or SELL")

        if assessment.momentum_state.lower() not in VALID_MOMENTUM_STATES:
            raise ValueError("Invalid momentum state")

        if assessment.current_price <= 0:
            raise ValueError("current_price must be positive")

        if assessment.entry_price <= 0:
            raise ValueError("entry_price must be positive")

        if assessment.partial_close_volume is not None:
            if float(assessment.partial_close_volume) <= 0:
                raise ValueError(
                    "partial_close_volume must be positive"
                )


def evaluate_position(assessment):
    """
    Convenience function for integrations that do not maintain
    a PositionPolicy instance.
    """
    return PositionPolicy().evaluate(assessment)
