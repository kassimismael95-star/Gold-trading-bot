import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class TestWorkerAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

        self.headers = {
            "X-Worker-Secret": "test-worker-secret"
        }

    @patch.dict(
        os.environ,
        {
            "WORKER_SHARED_SECRET": "test-worker-secret"
        }
    )
    @patch("execution.command_queue.claim_next_command")
    def test_get_next_command_returns_command(
        self,
        mock_claim_next_command
    ):
        mock_claim_next_command.return_value = {
            "id": "command-1",
            "worker_id": "worker-1",
            "command_type": "OPEN_POSITION",
            "status": "PROCESSING"
        }

        response = self.client.get(
            "/worker/commands/next",
            headers=self.headers
        )

        self.assertEqual(
            response.status_code,
            200
        )

        data = response.json()

        self.assertEqual(
            data["id"],
            "command-1"
        )

        self.assertEqual(
            data["status"],
            "PROCESSING"
        )

    @patch.dict(
        os.environ,
        {
            "WORKER_SHARED_SECRET": "test-worker-secret"
        }
    )
    @patch("execution.command_queue.claim_next_command")
    def test_get_next_command_returns_204_when_empty(
        self,
        mock_claim_next_command
    ):
        mock_claim_next_command.return_value = None

        response = self.client.get(
            "/worker/commands/next",
            headers=self.headers
        )

        self.assertEqual(
            response.status_code,
            204
        )

    @patch.dict(
        os.environ,
        {
            "WORKER_SHARED_SECRET": "test-worker-secret"
        }
    )
    def test_get_next_command_rejects_missing_secret(self):
        response = self.client.get(
            "/worker/commands/next"
        )

        self.assertEqual(
            response.status_code,
            401
        )

    @patch.dict(
        os.environ,
        {
            "WORKER_SHARED_SECRET": "test-worker-secret"
        }
    )
    def test_get_next_command_rejects_wrong_secret(self):
        response = self.client.get(
            "/worker/commands/next",
            headers={
                "X-Worker-Secret": "wrong-secret"
            }
        )

        self.assertEqual(
            response.status_code,
            401
        )

    @patch.dict(
        os.environ,
        {
            "WORKER_SHARED_SECRET": "test-worker-secret"
        }
    )
    @patch("execution.command_queue.complete_command")
    def test_complete_command_returns_success(
        self,
        mock_complete_command
    ):
        mock_complete_command.return_value = True

        response = self.client.post(
            "/worker/commands/command-1/complete",
            json={
                "ticket": 123456,
                "status": "EXECUTED"
            },
            headers=self.headers
        )

        self.assertEqual(
            response.status_code,
            200
        )

        self.assertEqual(
            response.json()["status"],
            "COMPLETED"
        )

    @patch.dict(
        os.environ,
        {
            "WORKER_SHARED_SECRET": "test-worker-secret"
        }
    )
    @patch("execution.command_queue.complete_command")
    def test_complete_command_returns_404_for_unknown_command(
        self,
        mock_complete_command
    ):
        mock_complete_command.return_value = False

        response = self.client.post(
            "/worker/commands/unknown-command/complete",
            json={},
            headers=self.headers
        )

        self.assertEqual(
            response.status_code,
            404
        )

    @patch.dict(
        os.environ,
        {
            "WORKER_SHARED_SECRET": "test-worker-secret"
        }
    )
    @patch("execution.command_queue.fail_command")
    def test_fail_command_returns_success(
        self,
        mock_fail_command
    ):
        mock_fail_command.return_value = True

        response = self.client.post(
            "/worker/commands/command-1/fail",
            json={
                "error_message": "MT5 order rejected"
            },
            headers=self.headers
        )

        self.assertEqual(
            response.status_code,
            200
        )

        self.assertEqual(
            response.json()["status"],
            "FAILED"
        )

    @patch.dict(
        os.environ,
        {
            "WORKER_SHARED_SECRET": "test-worker-secret"
        }
    )
    @patch("execution.command_queue.fail_command")
    def test_fail_command_returns_404_for_unknown_command(
        self,
        mock_fail_command
    ):
        mock_fail_command.return_value = False

        response = self.client.post(
            "/worker/commands/unknown-command/fail",
            json={
                "error_message": "MT5 order rejected"
            },
            headers=self.headers
        )

        self.assertEqual(
            response.status_code,
            404
        )

    @patch.dict(
        os.environ,
        {
            "WORKER_SHARED_SECRET": "test-worker-secret"
        }
    )
    @patch("execution.worker_registry.update_worker_heartbeat")
    def test_worker_heartbeat_returns_success(
        self,
        mock_update_worker_heartbeat
    ):
        mock_update_worker_heartbeat.return_value = True

        response = self.client.post(
            "/worker/heartbeat",
            json={
                "worker_id": "worker-1",
                "current_load": 1
            },
            headers=self.headers
        )

        self.assertEqual(
            response.status_code,
            200
        )

        self.assertEqual(
            response.json()["status"],
            "ONLINE"
        )

    @patch.dict(
        os.environ,
        {
            "WORKER_SHARED_SECRET": "test-worker-secret"
        }
    )
    @patch("execution.worker_registry.update_worker_heartbeat")
    def test_worker_heartbeat_returns_404_for_unknown_worker(
        self,
        mock_update_worker_heartbeat
    ):
        mock_update_worker_heartbeat.return_value = False

        response = self.client.post(
            "/worker/heartbeat",
            json={
                "worker_id": "unknown-worker",
                "current_load": 0
            },
            headers=self.headers
        )

        self.assertEqual(
            response.status_code,
            404
        )

    @patch.dict(
        os.environ,
        {
            "WORKER_SHARED_SECRET": "test-worker-secret"
        }
    )
    def test_worker_positions_requires_payload(self):
        response = self.client.post(
            "/worker/positions",
            headers=self.headers
        )

        self.assertEqual(
            response.status_code,
            422
        )


if __name__ == "__main__":
    unittest.main()
