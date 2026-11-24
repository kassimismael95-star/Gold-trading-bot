import requests
import os
from database.models import get_connection


def get_worker_api_url(worker_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT worker_id
        FROM worker_registry
        WHERE worker_id = %s
        AND worker_status = 'online'
    """, (worker_id,))

    worker = cursor.fetchone()

    cursor.close()
    connection.close()

    if not worker:
        raise ValueError(f"Worker {worker_id} is offline.")

    worker_url = os.environ.get("WORKER_API_URL")

    if not worker_url:
        raise ValueError("WORKER_API_URL is missing.")

    return worker_url.rstrip("/")


def send_command_to_worker(
    worker_id,
    command
):
    worker_url = get_worker_api_url(worker_id)

    worker_secret = os.environ.get("WORKER_SHARED_SECRET")

    if not worker_secret:
        raise ValueError("WORKER_SHARED_SECRET is missing.")

    response = requests.post(
        f"{worker_url}/execute-command",
        json=command,
        headers={
            "Authorization": f"Bearer {worker_secret}",
            "Content-Type": "application/json"
        },
        timeout=30
    )

    response.raise_for_status()

    return response.json()


def route_command_to_worker(
    worker_id,
    command_id,
    user_id,
    account_id,
    bot_session_id,
    command_type,
    symbol,
    direction=None,
    volume=None,
    stop_loss=None,
    take_profit=None
):
    command = {
        "command_id": command_id,
        "user_id": user_id,
        "account_id": account_id,
        "bot_session_id": bot_session_id,
        "command_type": command_type,
        "symbol": symbol,
        "direction": direction,
        "volume": volume,
        "stop_loss": stop_loss,
        "take_profit": take_profit
    }

    return send_command_to_worker(
        worker_id,
        command
    )
