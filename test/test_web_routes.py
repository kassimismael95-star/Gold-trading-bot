import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class TestWebRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

        self.headers = {
            "Authorization": "Bearer test-access-token"
        }

    @patch("web.auth.get_current_user")
    @patch("accounts.account_registry.list_accounts")
    def test_list_accounts_returns_user_accounts(
        self,
        mock_list_accounts,
        mock_get_current_user
    ):
        mock_get_current_user.return_value = {
            "id": 1,
            "email": "test@example.com"
        }

        mock_list_accounts.return_value = [
            {
                "id": 1,
                "user_id": 1,
                "broker_name": "Test Broker",
                "login": "123456",
                "server_name": "Test-Server",
                "status": "ACTIVE"
            }
        ]

        response = self.client.get(
            "/accounts",
            headers=self.headers
        )

        self.assertEqual(
            response.status_code,
            200
        )

        data = response.json()

        self.assertEqual(
            len(data),
            1
        )

        self.assertEqual(
            data[0]["user_id"],
            1
        )

    @patch("web.auth.get_current_user")
    @patch("core.bot_manager.create_bot_session")
    def test_create_bot_session_returns_session(
        self,
        mock_create_bot_session,
        mock_get_current_user
    ):
        mock_get_current_user.return_value = {
            "id": 1,
            "email": "test@example.com"
        }

        mock_create_bot_session.return_value = {
            "id": 1,
            "user_id": 1,
            "account_id": 1,
            "symbol": "XAUUSD",
            "status": "ACTIVE"
        }

        response = self.client.post(
            "/bots",
            json={
                "account_id": 1,
                "symbol": "XAUUSD",
                "risk_percent": 1.0,
                "max_positions": 3,
                "basket_target": 1.00
            },
            headers=self.headers
        )

        self.assertEqual(
            response.status_code,
            200
        )

        data = response.json()

        self.assertEqual(
            data["symbol"],
            "XAUUSD"
        )

        self.assertEqual(
            data["status"],
            "ACTIVE"
        )

    @patch("web.auth.get_current_user")
    @patch("core.bot_manager.create_bot_session")
    def test_create_bot_session_rejects_invalid_input(
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
            headers=self.headers
        )

        self.assertEqual(
            response.status_code,
            400
        )

        self.assertEqual(
            response.json()["detail"],
            "Invalid bot settings"
        )

    @patch("web.auth.get_current_user")
    @patch("core.bot_manager.get_bot_sessions")
    def test_list_bot_sessions_returns_sessions(
        self,
        mock_get_bot_sessions,
        mock_get_current_user
    ):
        mock_get_current_user.return_value = {
            "id": 1,
            "email": "test@example.com"
        }

        mock_get_bot_sessions.return_value = [
            {
                "id": 1,
                "user_id": 1,
                "account_id": 1,
                "symbol": "XAUUSD",
                "status": "ACTIVE"
            }
        ]

        response = self.client.get(
            "/bots",
            headers=self.headers
        )

        self.assertEqual(
            response.status_code,
            200
        )

        data = response.json()

        self.assertEqual(
            len(data),
            1
        )

        self.assertEqual(
            data[0]["symbol"],
            "XAUUSD"
        )

    @patch("web.auth.get_current_user")
    @patch("execution.command_queue.get_commands_for_user")
    def test_list_commands_returns_commands(
        self,
        mock_get_commands_for_user,
        mock_get_current_user
    ):
        mock_get_current_user.return_value = {
            "id": 1,
            "email": "test@example.com"
        }

        mock_get_commands_for_user.return_value = [
            {
                "id": "command-1",
                "user_id": 1,
                "account_id": 1,
                "bot_session_id": 1,
                "command_type": "OPEN_POSITION",
                "status": "PENDING"
            }
        ]

        response = self.client.get(
            "/commands",
            headers=self.headers
        )

        self.assertEqual(
            response.status_code,
            200
        )

        data = response.json()

        self.assertEqual(
            len(data),
            1
        )

        self.assertEqual(
            data[0]["command_type"],
            "OPEN_POSITION"
        )

    @patch("web.auth.get_current_user")
    @patch("execution.command_queue.get_commands_for_user")
    def test_list_commands_returns_empty_list(
        self,
        mock_get_commands_for_user,
        mock_get_current_user
    ):
        mock_get_current_user.return_value = {
            "id": 1,
            "email": "test@example.com"
        }

        mock_get_commands_for_user.return_value = []

        response = self.client.get(
            "/commands",
            headers=self.headers
        )

        self.assertEqual(
            response.status_code,
            200
        )

        self.assertEqual(
            response.json(),
            []
        )

    def test_accounts_requires_authentication(self):
        response = self.client.get(
            "/accounts"
        )

        self.assertEqual(
            response.status_code,
            401
        )

    def test_bots_requires_authentication(self):
        response = self.client.get(
            "/bots"
        )

        self.assertEqual(
            response.status_code,
            401
        )

    def test_commands_requires_authentication(self):
        response = self.client.get(
            "/commands"
        )

        self.assertEqual(
            response.status_code,
            401
        )


if __name__ == "__main__":
    unittest.main()
