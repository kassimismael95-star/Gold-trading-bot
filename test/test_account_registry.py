import unittest
from unittest.mock import patch, MagicMock

from accounts.account_registry import (
    add_account,
    get_account,
    list_accounts,
    update_account_status
)


class TestAccountRegistry(unittest.TestCase):
    def setUp(self):
        self.mock_connection = MagicMock()
        self.mock_cursor = MagicMock()

        self.mock_connection.cursor.return_value = (
            self.mock_cursor
        )

    @patch("accounts.account_registry.get_connection")
    @patch("accounts.account_registry.encrypt_password")
    def test_add_account_returns_account(
        self,
        mock_encrypt_password,
        mock_get_connection
    ):
        mock_encrypt_password.return_value = "encrypted-password"

        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.fetchone.return_value = {
            "id": 1,
            "user_id": 1,
            "broker_name": "Test Broker",
            "login": "123456",
            "server_name": "Test-Server",
            "status": "INACTIVE"
        }

        account = add_account(
            user_id=1,
            broker_name="Test Broker",
            login="123456",
            password="secret-password",
            server_name="Test-Server"
        )

        self.assertEqual(account["id"], 1)
        self.assertEqual(account["user_id"], 1)
        self.assertEqual(account["status"], "INACTIVE")

        mock_encrypt_password.assert_called_once_with(
            "secret-password"
        )

    @patch("accounts.account_registry.get_connection")
    def test_get_account_returns_user_account(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.fetchone.return_value = {
            "id": 1,
            "user_id": 1,
            "broker_name": "Test Broker",
            "login": "123456",
            "server_name": "Test-Server",
            "status": "ACTIVE"
        }

        account = get_account(
            user_id=1,
            account_id=1
        )

        self.assertEqual(account["user_id"], 1)
        self.assertEqual(account["status"], "ACTIVE")

    @patch("accounts.account_registry.get_connection")
    def test_get_account_returns_none_for_other_user(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.fetchone.return_value = None

        account = get_account(
            user_id=2,
            account_id=1
        )

        self.assertIsNone(account)

    @patch("accounts.account_registry.get_connection")
    def test_list_accounts_returns_user_accounts(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.fetchall.return_value = [
            {
                "id": 1,
                "user_id": 1,
                "broker_name": "Test Broker",
                "login": "123456",
                "server_name": "Test-Server",
                "status": "ACTIVE"
            }
        ]

        accounts = list_accounts(user_id=1)

        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["user_id"], 1)

    @patch("accounts.account_registry.get_connection")
    def test_update_account_status_returns_true(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.rowcount = 1

        updated = update_account_status(
            user_id=1,
            account_id=1,
            status="ACTIVE"
        )

        self.assertTrue(updated)

    @patch("accounts.account_registry.get_connection")
    def test_update_account_status_returns_false_for_other_user(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.rowcount = 0

        updated = update_account_status(
            user_id=2,
            account_id=1,
            status="ACTIVE"
        )

        self.assertFalse(updated)


if __name__ == "__main__":
    unittest.main()
