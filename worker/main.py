import logging
import os
import time
from typing import Any, Dict

from worker.config import (
    validate_worker_config,
    WORKER_ID,
    WORKER_NAME,
    WORKER_API_URL,
    MAX_CONCURRENT_COMMANDS,
    HEARTBEAT_INTERVAL_SECONDS,
    COMMAND_POLL_INTERVAL_SECONDS
)

from worker.control_plane_client import control_plane_client
from worker.command_executor import process_command
from worker.mt5_client import mt5_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

logger = logging.getLogger(__name__)

running = True


def register_worker() -> bool:
    try:
        response = control_plane_client.send_heartbeat(
            current_load=0
        )

        if response:
            logger.info(
                "Worker %s registered successfully",
                WORKER_ID
            )

        return response

    except Exception as error:
        logger.exception(
            "Worker registration failed: %s",
            str(error)
        )

        return False


def get_current_load() -> int:
    return 0


def handle_claimed_command(
    command: Dict[str, Any]
) -> None:
    command_id = command.get("id")

    if not command_id:
        logger.warning(
            "Claimed command has no ID"
        )

        return

    logger.info(
        "Processing command %s",
        command_id
    )

    result = process_command(
        command=command
    )

    if result["status"] == "COMPLETED":
        completed = control_plane_client.complete_command(
            command_id=command_id,
            result=result.get("result", {})
        )

        if completed:
            logger.info(
                "Command %s completed successfully",
                command_id
            )

        else:
            logger.warning(
                "Could not report completion for command %s",
                command_id
            )

    else:
        failed = control_plane_client.fail_command(
            command_id=command_id,
            error_message=result.get(
                "error_message",
                "Command failed"
            ),
            result=result.get("result")
        )

        if failed:
            logger.info(
                "Command %s marked as failed",
                command_id
            )

        else:
            logger.warning(
                "Could not report failure for command %s",
                command_id
            )


def run_worker_loop() -> None:
    last_heartbeat = 0

    logger.info(
        "Starting MT5 worker %s",
        WORKER_ID
    )

    while running:
        current_time = time.time()

        if current_time - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
            heartbeat_sent = control_plane_client.send_heartbeat(
                current_load=get_current_load()
            )

            if heartbeat_sent:
                last_heartbeat = current_time

            else:
                logger.warning(
                    "Heartbeat failed; will retry"
                )

        command = control_plane_client.claim_next_command()

        if command:
            handle_claimed_command(
                command=command
            )

        time.sleep(
            COMMAND_POLL_INTERVAL_SECONDS
        )


def main() -> None:
    global running

    try:
        config = validate_worker_config()

        logger.info(
            "Worker configuration validated for %s",
            config["worker_id"]
        )

        if not mt5_client.initialize():
            raise RuntimeError(
                "MT5 initialization failed"
            )

        if not mt5_client.login():
            raise RuntimeError(
                "MT5 login failed"
            )

        if not register_worker():
            raise RuntimeError(
                "Worker registration failed"
            )

        run_worker_loop()

    except KeyboardInterrupt:
        logger.info(
            "Worker stopped by user"
        )

    except Exception as error:
        logger.exception(
            "Worker fatal error: %s",
            str(error)
        )

    finally:
        running = False

        mt5_client.shutdown()

        logger.info(
            "MT5 worker shut down"
        )


if __name__ == "__main__":
    main()
