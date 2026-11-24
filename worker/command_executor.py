import logging
from typing import Any, Dict

from worker.mt5_client import mt5_client

logger = logging.getLogger(__name__)

ALLOWED_COMMAND_TYPES = [
    "OPEN_POSITION",
    "CLOSE_POSITION"
]

ALLOWED_DIRECTIONS = [
    "BUY",
    "SELL"
]


def validate_command(
    command: Dict[str, Any]
) -> None:
    if not isinstance(command, dict):
        raise ValueError(
            "Command must be a dictionary"
        )

    command_id = command.get("id")

    if not command_id:
        raise ValueError(
            "Command ID is required"
        )

    worker_id = command.get("worker_id")

    if not worker_id:
        raise ValueError(
            "Worker ID is required"
        )

    command_type = command.get("command_type")

    if command_type not in ALLOWED_COMMAND_TYPES:
        raise ValueError(
            "Invalid command type"
        )

    payload = command.get("payload")

    if not isinstance(payload, dict):
        raise ValueError(
            "Command payload is required"
        )

    symbol = payload.get("symbol")

    if not symbol:
        raise ValueError(
            "Symbol is required"
        )

    if command_type == "OPEN_POSITION":
        direction = payload.get("direction")

        if direction not in ALLOWED_DIRECTIONS:
            raise ValueError(
                "Invalid direction"
            )

        volume = payload.get("volume")

        if not isinstance(volume, (int, float)):
            raise ValueError(
                "Volume must be a number"
            )

        if volume <= 0:
            raise ValueError(
                "Volume must be greater than zero"
            )

    if command_type == "CLOSE_POSITION":
        ticket = payload.get("ticket")

        if not ticket:
            raise ValueError(
                "Ticket is required"
            )


def execute_open_position(
    payload: Dict[str, Any]
) -> Dict[str, Any]:
    symbol = payload["symbol"]
    direction = payload["direction"]
    volume = payload["volume"]

    stop_loss = payload.get("stop_loss")
    take_profit = payload.get("take_profit")

    symbol_info = mt5_client.get_symbol_info(
        symbol=symbol
    )

    if symbol_info is None:
        return {
            "status": "ERROR",
            "reason": "Symbol unavailable"
        }

    if volume < symbol_info["volume_min"]:
        return {
            "status": "REJECTED",
            "reason": "Volume below broker minimum"
        }

    if volume > symbol_info["volume_max"]:
        return {
            "status": "REJECTED",
            "reason": "Volume above broker maximum"
        }

    return mt5_client.open_position(
        symbol=symbol,
        direction=direction,
        volume=volume,
        stop_loss=stop_loss,
        take_profit=take_profit
    )


def execute_close_position(
    payload: Dict[str, Any]
) -> Dict[str, Any]:
    ticket = payload["ticket"]

    volume = payload.get("volume")

    return mt5_client.close_position(
        ticket=ticket,
        volume=volume
    )


def execute_command(
    command: Dict[str, Any]
) -> Dict[str, Any]:
    command_type = command["command_type"]
    payload = command["payload"]

    if command_type == "OPEN_POSITION":
        return execute_open_position(
            payload=payload
        )

    if command_type == "CLOSE_POSITION":
        return execute_close_position(
            payload=payload
        )

    return {
        "status": "ERROR",
        "reason": "Unsupported command type"
    }


def process_command(
    command: Dict[str, Any]
) -> Dict[str, Any]:
    try:
        validate_command(
            command=command
        )
    except ValueError as error:
        logger.warning(
            "Invalid command %s: %s",
            command.get("id"),
            str(error)
        )

        return {
            "command_id": command.get("id"),
            "status": "FAILED",
            "error_message": str(error)
        }

    try:
        result = execute_command(
            command=command
        )
    except Exception as error:
        logger.exception(
            "Command execution failed: %s",
            command.get("id")
        )

        return {
            "command_id": command.get("id"),
            "status": "FAILED",
            "error_message": str(error)
        }

    if result.get("status") == "EXECUTED":
        return {
            "command_id": command.get("id"),
            "status": "COMPLETED",
            "result": result
        }

    return {
        "command_id": command.get("id"),
        "status": "FAILED",
        "error_message": result.get(
            "reason",
            "Command execution failed"
        ),
        "result": result
    }
