import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class TestIntegrationFlow(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("web.auth.get_current_user")
    @patch("core.license_manager.activate_license")
    @patch("accounts.account_registry.add_account")
    @patch("core.bot_manager.create_bot_session")
    @patch("execution.command_queue.create_command")
    @patch("execution.command_queue.claim_next_command")
    @patch("execution.command_queue.complete_command")
    def test_full_control_plane_flow(
        self,
        mock_complete_command,
        mock_claim_next_command,
        mock_create_command,
        mock_create_bot_session,
        mock_add_account,
        mock_activate_license,
        mock_get_current_user
    ):
        mock_get_current_user.return_value = {
            "id": 1,
            "email": "test@example.com"
        }

        mock_activate_license.return_value = {
            "id": 1,
            "user_id": 1,
            "license_key": "BOSSMODE99",
            "status": "ACTIVE"
        }

        mock_add_account.return_value = {
            "id": 1,
            "user_id": 1,
            "broker_name": "Test Broker",
            "login": "123456",
            "server_name": "Test-Server",
            "status": "INACTIVE"
        }

        mock_create_bot_session.return_value = {
            "id": 1,
            "user_id": 1,
            "account_id": 1,
            "symbol": "XAUUSD",
            "status": "ACTIVE"
        }

        mock_create_command.return_value = {
            "id": "command-1",
            "user_id": 1,
            "account_id": 1,
            "bot_session_id": 1,
            "worker_id": "worker-1",
            "command_type": "OPEN_POSITION",
            "status": "PENDING"
        }

        mock_claim_next_command.return_value = {
            "id": "command-1",
            "worker_id": "worker-1",
            "command_type": "OPEN_POSITION",
            "status": "PROCESSING"
        }

        mock_complete_command.return_value = True

        license_response = self.client.post(
            "/licenses/activate",
            json={
                "license_key": "BOSSMODE99"
            },
            headers={
                "Authorization": "Bearer test-token"
            }
        )

        self.assertEqual(
            license_response.status_code,
            200
        )

        self.assertEqual(
            license_response.json()["status"],
            "ACTIVE"
        )

        account_response = self.client.post(
            "/accounts",
            json={
                "broker_name": "Test Broker",
                "login": "123456",
                "password": "test-password",
                "server_name": "Test-Server"
            },
            headers={
                "Authorization": "Bearer test-token"
            }
        )

        self.assertEqual(
            account_response.status_code,
            200
        )

        self.assertEqual(
            account_response.json()["user_id"],
            1
        )

        bot_response = self.client.post(
            "/bots",
            json={
                "account_id": 1,
                "symbol": "XAUUSD",
                "risk_percent": 1.0,
                "max_positions": 3,
                "basket_target": 1.00
            },
            headers={
                "Authorization": "Bearer test-token"
            }
        )

        self.assertEqual(
            bot_response.status_code,
            200
        )

        self.assertEqual(
            bot_response.json()["symbol"],
            "XAUUSD"
        )

        command_response = self.client.post(
            "/commands",
            json={
                "account_id": 1,
                "bot_session_id": 1,
                "worker_id": "worker-1",
                "command_type": "OPEN_POSITION",
                "payload": {
                    "symbol": "XAUUSD",
                    "direction": "BUY",
                    "volume": 0.01,
                    "stop_loss": 2295.00,
                    "take_profit": 2305.00
                }
            },
            headers={
                "Authorization": "Bearer test-token"
            }
        )

        self.assertEqual(
            command_response.status_code,
            200
        )

        self.assertEqual(
            command_response.json()["status"],
            "PENDING"
        )

        worker_response = self.client.get(
            "/worker/commands/next",
            headers={
                "X-Worker-Secret": "test-worker-secret"
            }
        )

        self.assertEqual(
            worker_response.status_code,
            200
        )

        self.assertEqual(
            worker_response.json()["id"],
            "command-1"
        )

        complete_response = self.client.post(
            "/worker/commands/command-1/complete",
            json={
                "ticket": 123456,
                "status": "EXECUTED"
            },
            headers={
                "X-Worker-Secret": "test-worker-secret"
            }
        )

        self.assertEqual(
            complete_response.status_code,
            200
        )

        self.assertEqual(
            complete_response.json()["status"],
            "COMPLETED"
        )

    @patch("web.auth.get_current_user")
    @patch("core.license_manager.activate_license")
    def test_flow_rejects_invalid_license(
        self,
        mock_activate_license,
        mock_get_current_user
    ):
        mock_get_current_user.return_value = {
            "id": 1,
            "email": "test@example.com"
        }

        mock_activate_license.side_effect = ValueError(
            "Invalid license key"
        )

        response = self.client.post(
            "/licenses/activate",
            json={
                "license_key": "INVALID-KEY"
            },
            headers={
                "Authorization": "Bearer test-token"
            }
        )

        self.assertEqual(
            response.status_code,
            400
        )

        self.assertEqual(
            response.json()["detail"],
            "Invalid license key"
        )

    @patch("web.auth.get_current_user")
    @patch("core.bot_manager.create_bot_session")
    def test_flow_rejects_invalid_bot_settings(
        self,
        mock_create_bot_session,
        mock_get_current_user
    ):
        mock_get_current_user.return_value = {
            "id": 1,
            "email": "test@example.com"
        }

        mock_create_bot_session.side_effect = ValueError(
            "Invalid bot settings"
        )

        response = self.client.post(
            "/bots",
            json={
                "account_id": 1,
                "symbol": "XAUUSD",
                "risk_percent": 1.0,
                "max_positions": 3,
                "basket_target": 1.00
            },
            headers={
                "Authorization": "Bearer test-token"
            }
        )

        self.assertEqual(
            response.status_code,
            400
        )

        self.assertEqual(
            response.json()["detail"],
            "Invalid bot settings"
        )


if __name__ == "__main__":
    unittest.main()
