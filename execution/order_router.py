import os
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class OrderRouteResult:
    success: bool
    worker_id: str | None
    order_ref: str | None
    message: str
    response: dict[str, Any] | None = None


class OrderRouter:
    """
    Routes original Gold Scalper execution commands to the correct
    isolated Windows MT5 worker.

    Preserves the original order types:
    - BUY
    - SELL
    - CLOSE_BASKET

    Does not change:
    - Strategy
    - Lot sizing
    - SL/TP calculation
    - Basket behavior
    - Bot signature
    """

    def __init__(self, database, worker_registry):
        self.database = database
        self.worker_registry = worker_registry

    def _worker_api_url(self, worker_id: str) -> str:
        base_url = os.environ.get("WORKER_API_URL", "").strip().rstrip("/")

        if not base_url:
            raise ValueError(
                "WORKER_API_URL is empty. "
                "Set it in the Render environment variables."
            )

        return f"{base_url}/workers/{worker_id}/commands"

    async def route_command(
        self,
        account_id: str,
        command: dict[str, Any],
    ) -> OrderRouteResult:
        if not account_id:
            return OrderRouteResult(
                success=False,
                worker_id=None,
                order_ref=None,
                message="Account ID is required.",
            )

        if not isinstance(command, dict):
            return OrderRouteResult(
                success=False,
                worker_id=None,
                order_ref=None,
                message="Command must be a JSON object.",
            )

        command_type = str(
            command.get("command_type", "")
        ).strip().upper()

        if command_type not in ["BUY", "SELL", "CLOSE_BASKET"]:
            return OrderRouteResult(
                success=False,
                worker_id=None,
                order_ref=None,
                message=(
                    "Unsupported command type. "
                    "Allowed commands: BUY, SELL, CLOSE_BASKET."
                ),
            )

        account = self.database.get_account(account_id)

        if not account:
            return OrderRouteResult(
                success=False,
                worker_id=None,
                order_ref=None,
                message="Trading account not found.",
            )

        worker_id = account.get("worker_id")

        if not worker_id:
            return OrderRouteResult(
                success=False,
                worker_id=None,
                order_ref=None,
                message="Account is not assigned to an MT5 worker.",
            )

        worker = self.worker_registry.get_worker(worker_id)

        if not worker:
            return OrderRouteResult(
                success=False,
                worker_id=worker_id,
                order_ref=None,
                message="Assigned MT5 worker not found.",
            )

        if worker.get("status") != "ACTIVE":
            return OrderRouteResult(
                success=False,
                worker_id=worker_id,
                order_ref=None,
                message=(
                    f"MT5 worker {worker_id} is not active. "
                    "Order was not sent."
                ),
            )

        command["account_id"] = account_id
        command["worker_id"] = worker_id

        url = self._worker_api_url(worker_id)
        shared_secret = os.environ.get("WORKER_SHARED_SECRET", "").strip()

        if not shared_secret:
            return OrderRouteResult(
                success=False,
                worker_id=worker_id,
                order_ref=None,
                message=(
                    "WORKER_SHARED_SECRET is empty. "
                    "Set it in the Render environment variables."
                ),
            )

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    url,
                    json=command,
                    headers={
                        "X-Worker-Secret": shared_secret,
                        "Content-Type": "application/json",
                    },
                )

            if response.status_code not in [200, 201, 202]:
                return OrderRouteResult(
                    success=False,
                    worker_id=worker_id,
                    order_ref=None,
                    message=(
                        f"MT5 worker rejected command with status "
                        f"{response.status_code}."
                    ),
                    response=self._safe_json(response),
                )

            response_data = self._safe_json(response)

            return OrderRouteResult(
                success=True,
                worker_id=worker_id,
                order_ref=response_data.get("order_ref"),
                message="Command delivered to the assigned MT5 worker.",
                response=response_data,
            )

        except httpx.TimeoutException:
            return OrderRouteResult(
                success=False,
                worker_id=worker_id,
                order_ref=None,
                message="MT5 worker did not respond in time.",
            )

        except Exception as error:
            return OrderRouteResult(
                success=False,
                worker_id=worker_id,
                order_ref=None,
                message=f"Failed to deliver command: {error}",
            )

    def _safe_json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()

            if isinstance(data, dict):
                return data

            return {"raw_response": data}

        except Exception:
            return {
                "raw_response": response.text,
            }
