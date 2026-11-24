from dataclasses import dataclass
from typing import Any

from worker.mt5_client import MT5Client


@dataclass
class CommandResult:
    success: bool
    message: str
    command_type: str
    account_id: str
    worker_id: str
    response: dict[str, Any] | None = None


class CommandExecutor:
    """
    Executes original Gold Scalper commands on one isolated MT5 terminal.

    Preserves:
    - BUY execution
    - SELL execution
    - CLOSE_BASKET execution
    - Original bot signature
    - Original symbol resolution
    - Original SL/TP submission
    """

    def __init__(self, mt5_client: MT5Client):
        self.mt5_client = mt5_client

    def execute(
        self,
        command: dict[str, Any],
    ) -> CommandResult:
        command_type = str(
            command.get("command_type", "")
        ).strip().upper()

        account_id = str(
            command.get("account_id", "")
        ).strip()

        worker_id = str(
            command.get("worker_id", "")
        ).strip()

        if command_type not in ["BUY", "SELL", "CLOSE_BASKET"]:
            return CommandResult(
                success=False,
                message=(
                    "Unsupported command type. "
                    "Allowed commands: BUY, SELL, CLOSE_BASKET."
                ),
                command_type=command_type,
                account_id=account_id,
                worker_id=worker_id,
            )

        if not account_id:
            return CommandResult(
                success=False,
                message="Account ID is required.",
                command_type=command_type,
                account_id=account_id,
                worker_id=worker_id,
            )

        if not worker_id:
            return CommandResult(
                success=False,
                message="Worker ID is required.",
                command_type=command_type,
                account_id=account_id,
                worker_id=worker_id,
            )

        symbol = self.mt5_client.resolve_gold_symbol(
            str(command.get("symbol", "XAUUSDm")).strip()
        )

        if command_type == "CLOSE_BASKET":
            close_result = self.mt5_client.close_all_positions(symbol)

            return CommandResult(
                success=close_result["success"],
                message=close_result["message"],
                command_type=command_type,
                account_id=account_id,
                worker_id=worker_id,
                response=close_result,
            )

        direction = command_type

        try:
            volume = float(command.get("volume", 0))

            stop_loss = float(command.get("stop_loss", 0))

            take_profit = float(command.get("take_profit", 0))

        except (TypeError, ValueError):
            return CommandResult(
                success=False,
                message="Volume, stop loss, and take profit must be numeric.",
                command_type=command_type,
                account_id=account_id,
                worker_id=worker_id,
            )

        if volume <= 0:
            return CommandResult(
                success=False,
                message="Volume must be greater than zero.",
                command_type=command_type,
                account_id=account_id,
                worker_id=worker_id,
            )

        if stop_loss <= 0 or take_profit <= 0:
            return CommandResult(
                success=False,
                message="Stop loss and take profit are required.",
                command_type=command_type,
                account_id=account_id,
                worker_id=worker_id,
            )

        comment = str(
            command.get(
                "comment",
                "BALANCED-SCALP",
            )
        ).strip()

        order_result = self.mt5_client.open_market_order(
            symbol=symbol,
            direction=direction,
            volume=volume,
            stop_loss=stop_loss,
            take_profit=take_profit,
            comment=comment,
        )

        return CommandResult(
            success=order_result["success"],
            message=order_result["message"],
            command_type=command_type,
            account_id=account_id,
            worker_id=worker_id,
            response=order_result,
        )
