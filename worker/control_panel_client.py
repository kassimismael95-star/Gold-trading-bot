import logging
from typing import Any, Dict, Optional

import requests

from worker.config import (
    CONTROL_PLANE_URL,
    WORKER_SHARED_SECRET,
    WORKER_ID
)

logger = logging.getLogger(__name__)


class ControlPlaneClient:
    def __init__(
        self,
        control_plane_url: str = CONTROL_PLANE_URL,
        worker_secret: str = WORKER_SHARED_SECRET,
        worker_id: str = WORKER_ID
    ):
        self.control_plane_url = control_plane_url.rstrip("/")
        self.worker_secret = worker_secret
        self.worker_id = worker_id

    def _headers(self) -> Dict[str, str]:
        return {
            "X-Worker-Secret": self.worker_secret,
            "Content-Type": "application/json"
        }

    def send_heartbeat(
        self,
        current_load: int = 0
    ) -> bool:
        try:
            response = requests.post(
                f"{self.control_plane_url}/worker/heartbeat",
                json={
                    "worker_id": self.worker_id,
                    "current_load": current_load
                },
                headers=self._headers(),
                timeout=10
            )

            if response.status_code == 200:
                return True

            logger.warning(
                "Heartbeat failed with status %s: %s",
                response.status_code,
                response.text
            )

            return False

        except requests.RequestException as error:
            logger.error(
                "Heartbeat request failed: %s",
                str(error)
            )

            return False

    def claim_next_command(self) -> Optional[Dict[str, Any]]:
        try:
            response = requests.get(
                f"{self.control_plane_url}/worker/commands/next",
                headers=self._headers(),
                timeout=10
            )

            if response.status_code == 204:
                return None

            if response.status_code != 200:
                logger.warning(
                    "Claim command failed with status %s: %s",
                    response.status_code,
                    response.text
                )

                return None

            return response.json()

        except requests.RequestException as error:
            logger.error(
                "Claim command request failed: %s",
                str(error)
            )

            return None

    def complete_command(
        self,
        command_id: str,
        result: Dict[str, Any]
    ) -> bool:
        try:
            response = requests.post(
                f"{self.control_plane_url}/worker/commands/{command_id}/complete",
                json=result,
                headers=self._headers(),
                timeout=10
            )

            if response.status_code == 200:
                return True

            logger.warning(
                "Complete command failed with status %s: %s",
                response.status_code,
                response.text
            )

            return False

        except requests.RequestException as error:
            logger.error(
                "Complete command request failed: %s",
                str(error)
            )

            return False

    def fail_command(
        self,
        command_id: str,
        error_message: str,
        result: Optional[Dict[str, Any]] = None
    ) -> bool:
        payload = {
            "error_message": error_message
        }

        if result is not None:
            payload["result"] = result

        try:
            response = requests.post(
                f"{self.control_plane_url}/worker/commands/{command_id}/fail",
                json=payload,
                headers=self._headers(),
                timeout=10
            )

            if response.status_code == 200:
                return True

            logger.warning(
                "Fail command failed with status %s: %s",
                response.status_code,
                response.text
            )

            return False

        except requests.RequestException as error:
            logger.error(
                "Fail command request failed: %s",
                str(error)
            )

            return False


control_plane_client = ControlPlaneClient()
