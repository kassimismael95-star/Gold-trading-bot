
import asyncio
import inspect
from typing import Any, Callable, Dict, Optional

from trading.position_manager import PositionManager, get_position_value


class MasterLiveMarketController:
    """
    Coordinates independent management of broker-confirmed positions.

    Responsibilities:
    - Keep positions isolated by account.
    - Receive live market snapshots.
    - Request decisions from the intelligence evaluator.
    - Prepare individual position-management plans.
    - Execute plans through an injected broker adapter.
    - Verify changes against actual broker positions.

    This controller does not open new trades.
    It does not invent trading thresholds or strategy rules.
    """

    def __init__(
        self,
        position_manager: Optional[PositionManager] = None,
        intelligence_evaluator: Optional[Callable] = None,
        broker_action: Optional[Callable] = None,
        broker_snapshot: Optional[Callable] = None
    ):
        self.position_manager = position_manager or PositionManager()

        self.intelligence_evaluator = intelligence_evaluator
        self.broker_action = broker_action
        self.broker_snapshot = broker_snapshot

        self.account_locks: Dict[str, asyncio.Lock] = {}
        self.last_market_snapshots: Dict[str, Dict[str, Any]] = {}

        self.running = False
        self.last_errors = {}

    def _account_lock(self, account_id):
        account_id = str(account_id)

        if account_id not in self.account_locks:
            self.account_locks[account_id] = asyncio.Lock()

        return self.account_locks[account_id]

    @staticmethod
    async def _resolve(value):
        if inspect.isawaitable(value):
            return await value
        return value

    @staticmethod
    def _read_number(position, *names):
        value = get_position_value(position, *names)

        if value is None:
            return None

        return float(value)

    def register_confirmed_position(self, account_id, broker_position):
        """
        Register a position only after it exists at the broker.
        """
        return self.position_manager.register_broker_position(
            account_id,
            broker_position
        )

    def reconcile_account_positions(self, account_id, broker_positions):
        """
        Reconcile the account's internal position records against
        the positions currently reported by the broker.

        Existing position history is preserved.
        Newly discovered positions are registered.
        Positions missing from the broker are marked closed only
        after the broker snapshot has been successfully obtained.
        """
        account_id = str(account_id)

        broker_positions = list(broker_positions)

        broker_ids = set()

        for broker_position in broker_positions:
            position_id = get_position_value(
                broker_position, "id", "position_id", "ticket"
            )

            if position_id is None:
                continue

            position_id = str(position_id)
            broker_ids.add(position_id)

            self.position_manager.register_broker_position(
                account_id,
                broker_position
            )

        tracked = self.position_manager.get_account_positions(
            account_id
        )

        for position_id, state in tracked.items():
            if position_id not in broker_ids:
                self.position_manager.mark_closed(
                    position_id,
                    "position_absent_from_successful_broker_snapshot"
                )

        return {
            "account_id": account_id,
            "broker_position_count": len(broker_ids),
            "tracked_position_count": len(
                self.position_manager.get_account_positions(account_id)
            ),
            "reconciled": True
        }

    async def publish_market_snapshot(self, account_id, snapshot):
        """
        Store the latest live market information for an account.

        Expected snapshot fields depend on the intelligence evaluator.
        No entry or exit decisions are made here.
        """
        account_id = str(account_id)

        if not isinstance(snapshot, dict):
            raise TypeError("Market snapshot must be a dictionary")

        self.last_market_snapshots[account_id] = dict(snapshot)

        return {
            "account_id": account_id,
            "snapshot_received": True
        }

    async def evaluate_account(self, account_id, market_snapshot=None):
        """
        Evaluate every tracked position belonging to one account.

        The intelligence evaluator must return a dictionary containing
        any requested management changes.
        """
        account_id = str(account_id)

        if self.intelligence_evaluator is None:
            raise RuntimeError("Intelligence evaluator is not configured")

        if market_snapshot is None:
            market_snapshot = self.last_market_snapshots.get(account_id)

        if market_snapshot is None:
            raise RuntimeError("No market snapshot is available")

        results = []

        async with self._account_lock(account_id):
            positions = self.position_manager.get_account_positions(
                account_id
            )

            for position_id, state in list(positions.items()):
                try:
                    decision = await self._resolve(
                        self.intelligence_evaluator(
                            state,
                            market_snapshot
                        )
                    )

                    if not isinstance(decision, dict):
                        raise TypeError(
                            "Intelligence evaluator must return a dictionary"
                        )

                    state.momentum_state = str(
                        decision.get(
                            "momentum_state",
                            state.momentum_state
                        )
                    )

                    state.reversal_state = str(
                        decision.get(
                            "reversal_state",
                            state.reversal_state
                        )
                    )

                    plan = self.position_manager.create_management_plan(
                        position_id=position_id,
                        new_stop_loss=decision.get("stop_loss"),
                        new_take_profit=decision.get("take_profit"),
                        partial_close_volume=decision.get(
                            "partial_close_volume"
                        ),
                        close_position=decision.get(
                            "close_position",
                            False
                        ),
                        reason=decision.get("reason")
                    )

                    if self._plan_has_actions(plan):
                        execution_result = await self.execute_plan(plan)

                    else:
                        execution_result = {
                            "executed": False,
                            "reason": "no_management_action_requested"
                        }

                    results.append({
                        "position_id": position_id,
                        "decision": decision,
                        "plan": plan,
                        "execution": execution_result
                    })

                except Exception as exc:
                    self.last_errors[position_id] = str(exc)

                    results.append({
                        "position_id": position_id,
                        "error": str(exc),
                        "executed": False
                    })

        return {
            "account_id": account_id,
            "positions_evaluated": len(results),
            "results": results
        }

    @staticmethod
    def _plan_has_actions(plan):
        return any((
            plan.get("close_position"),
            plan.get("partial_close_volume") is not None,
            plan.get("stop_loss") is not None,
            plan.get("take_profit") is not None
        ))

    async def execute_plan(self, plan):
        """
        Execute a management plan using the configured broker adapter.

        Required broker_action signature:

            broker_action(
                account_id,
                position_id,
                action,
                payload
            )

        Required broker_snapshot signature:

            broker_snapshot(account_id)

        The broker snapshot must return the account's current
        open positions after execution.
        """
        if self.broker_action is None:
            raise RuntimeError("Broker action adapter is not configured")

        if self.broker_snapshot is None:
            raise RuntimeError("Broker snapshot adapter is not configured")

        account_id = str(plan["account_id"])
        position_id = str(plan["position_id"])

        if plan.get("close_position"):
            action = "close"
            payload = {}

        elif plan.get("partial_close_volume") is not None:
            action = "partial_close"
            payload = {
                "volume": plan["partial_close_volume"]
            }

        else:
            action = "modify"
            payload = {
                "stop_loss": plan.get("stop_loss"),
                "take_profit": plan.get("take_profit")
            }

        action_result = await self._resolve(
            self.broker_action(
                account_id,
                position_id,
                action,
                payload
            )
        )

        # An API response alone does not prove that the broker
        # completed the requested operation.
        broker_positions = await self._resolve(
            self.broker_snapshot(account_id)
        )

        if broker_positions is None:
            raise RuntimeError(
                "Broker verification returned no position snapshot"
            )

        broker_positions = list(broker_positions)

        confirmed_position = None

        for position in broker_positions:
            broker_id = get_position_value(
                position, "id", "position_id", "ticket"
            )

            if broker_id is not None and str(broker_id) == position_id:
                confirmed_position = position
                break

        if action == "close":
            if confirmed_position is not None:
                raise RuntimeError(
                    "Broker still reports the position as open"
                )

            self.position_manager.mark_closed(
                position_id,
                plan.get("reason") or "controller_close"
            )

            return {
                "executed": True,
                "verified": True,
                "action": action,
                "broker_result": action_result
            }

        if confirmed_position is None:
            raise RuntimeError(
                "Position disappeared during verification; "
                "requested modification was not confirmed"
            )

        actual_sl = self._read_number(
            confirmed_position, "stop_loss", "sl"
        )

        actual_tp = self._read_number(
            confirmed_position, "take_profit", "tp"
        )

        actual_volume = self._read_number(
            confirmed_position, "volume", "lots"
        )

        if action == "modify":
            requested_sl = plan.get("stop_loss")
            requested_tp = plan.get("take_profit")

            if requested_sl is not None:
                if actual_sl is None or abs(actual_sl - requested_sl) > 1e-8:
                    raise RuntimeError(
                        "Broker stop-loss change was not verified"
                    )

            if requested_tp is not None:
                if actual_tp is None or abs(actual_tp - requested_tp) > 1e-8:
                    raise RuntimeError(
                        "Broker take-profit change was not verified"
                    )

        if action == "partial_close":
            original = self.position_manager.get_position(position_id)

            if actual_volume is None or actual_volume >= original.volume:
                raise RuntimeError(
                    "Partial close was not verified by broker volume"
                )

        self.position_manager.confirm_broker_update(
            position_id=position_id,
            stop_loss=actual_sl,
            take_profit=actual_tp,
            remaining_volume=actual_volume,
            partial_close=(action == "partial_close")
        )

        return {
            "executed": True,
            "verified": True,
            "action": action,
            "broker_result": action_result,
            "verified_stop_loss": actual_sl,
            "verified_take_profit": actual_tp,
            "verified_volume": actual_volume
        }

    async def run_account_cycle(self, account_id, market_snapshot):
        """
        One management cycle for one account.

        The calling application supplies the latest market snapshot.
        This method does not start an independent infinite loop.
        """
        account_id = str(account_id)

        await self.publish_market_snapshot(
            account_id,
            market_snapshot
        )

        return await self.evaluate_account(
            account_id,
            market_snapshot
        )

    def get_account_status(self, account_id):
        account_id = str(account_id)

        positions = self.position_manager.get_account_positions(
            account_id
        )

        return {
            "account_id": account_id,
            "active_positions": len(positions),
            "positions": {
                position_id: {
                    "symbol": state.symbol,
                    "direction": state.direction,
                    "entry_price": state.entry_price,
                    "volume": state.volume,
                    "initial_stop_loss": state.initial_stop_loss,
                    "current_stop_loss": state.current_stop_loss,
                    "initial_take_profit": state.initial_take_profit,
                    "current_take_profit": state.current_take_profit,
                    "current_unrealised_profit": (
                        state.current_unrealised_profit
                    ),
                    "maximum_unrealised_profit": (
                        state.maximum_unrealised_profit
                    ),
                    "momentum_state": state.momentum_state,
                    "reversal_state": state.reversal_state,
                    "management_state": state.management_state
                }
                for position_id, state in positions.items()
            }
        }
