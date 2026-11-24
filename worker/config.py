import os
from dotenv import load_dotenv

load_dotenv()


CONTROL_PLANE_URL = os.getenv(
    "CONTROL_PLANE_URL",
    "http://localhost:8000"
)

WORKER_SHARED_SECRET = os.getenv(
    "WORKER_SHARED_SECRET",
    ""
)

WORKER_ID = os.getenv(
    "WORKER_ID",
    "worker-1"
)

WORKER_NAME = os.getenv(
    "WORKER_NAME",
    "Primary MT5 Worker"
)

WORKER_API_URL = os.getenv(
    "WORKER_API_URL",
    "http://localhost:9000"
)

MT5_LOGIN = os.getenv(
    "MT5_LOGIN",
    ""
)

MT5_PASSWORD = os.getenv(
    "MT5_PASSWORD",
    ""
)

MT5_SERVER = os.getenv(
    "MT5_SERVER",
    ""
)

MT5_TERMINAL_PATH = os.getenv(
    "MT5_TERMINAL_PATH",
    ""
)

HEARTBEAT_INTERVAL_SECONDS = int(
    os.getenv(
        "HEARTBEAT_INTERVAL_SECONDS",
        "15"
    )
)

COMMAND_POLL_INTERVAL_SECONDS = int(
    os.getenv(
        "COMMAND_POLL_INTERVAL_SECONDS",
        "2"
    )
)

MAX_CONCURRENT_COMMANDS = int(
    os.getenv(
        "MAX_CONCURRENT_COMMANDS",
        "5"
    )
)


def validate_worker_config():
    missing = []

    if not WORKER_SHARED_SECRET:
        missing.append("WORKER_SHARED_SECRET")

    if not MT5_LOGIN:
        missing.append("MT5_LOGIN")

    if not MT5_PASSWORD:
        missing.append("MT5_PASSWORD")

    if not MT5_SERVER:
        missing.append("MT5_SERVER")

    if missing:
        raise RuntimeError(
            "Missing required worker configuration: "
            + ", ".join(missing)
        )

    return {
        "control_plane_url": CONTROL_PLANE_URL,
        "worker_id": WORKER_ID,
        "worker_name": WORKER_NAME,
        "worker_api_url": WORKER_API_URL,
        "mt5_server": MT5_SERVER,
        "heartbeat_interval_seconds": HEARTBEAT_INTERVAL_SECONDS,
        "command_poll_interval_seconds": COMMAND_POLL_INTERVAL_SECONDS,
        "max_concurrent_commands": MAX_CONCURRENT_COMMANDS
    }
