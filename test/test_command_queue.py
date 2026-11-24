import unittest
from unittest.mock import patch, MagicMock

from execution.command_queue import (
    create_command,
    claim_next_command,
    complete_command,
    fail_command
)


class TestCommandQueue(unittest.TestCase):
    def setUp(self):
        self.mock_connection = MagicMock()
        self.mock_cursor = MagicMock()

        self.mock_connection.cursor.return_value = (
            self.mock_cursor
        )

    @patch("execution.command_queue.get_connection")
    def test_create_command_returns_pending_command(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.fetchone.return_value = {
            "id": "command-1",
            "user_id": 1,
            "account_id": 1,
            "bot_session_id": 1,
            "worker_id": "worker-1",
            "command_type": "OPEN_POSITION",
            "status": "PENDING"
        }

        command = create_command(
            user_id=1,
            account_id=1,
            bot_session_id=1,
            worker_id="worker-1",
            command_type="OPEN_POSITION",
            payload={
                "symbol": "XAUUSD",
                "direction": "BUY",
                "volume": 0.01
            }
        )

        self.assertEqual(command["id"], "command-1")
        self.assertEqual(command["status"], "PENDING")
        self.assertEqual(command["worker_id"], "worker-1")

    @patch("execution.command_queue.get_connection")
    def test_claim_next_command_returns_pending_command(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.fetchone.return_value = {
            "id": "command-1",
            "worker_id": "worker-1",
            "command_type": "OPEN_POSITION",
            "status": "PROCESSING"
        }

        command = claim_next_command(
            worker_id="worker-1"
        )

        self.assertEqual(command["id"], "command-1")
        self.assertEqual(command["status"], "PROCESSING")

    @patch("execution.command_queue.get_connection")
    def test_claim_next_command_returns_none_when_empty(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.fetchone.return_value = None

        command = claim_next_command(
            worker_id="worker-1"
        )

        self.assertIsNone(command)

    @patch("execution.command_queue.get_connection")
    def test_complete_command_returns_true(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.rowcount = 1

        completed = complete_command(
            command_id="command-1",
            result={
                "ticket": 123456,
                "status": "EXECUTED"
            }
        )

        self.assertTrue(completed)

    @patch("execution.command_queue.get_connection")
    def test_complete_command_returns_false_for_unknown_command(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.rowcount = 0

        completed = complete_command(
            command_id="unknown-command",
            result={}
        )

        self.assertFalse(completed)

    @patch("execution.command_queue.get_connection")
    def test_fail_command_returns_true(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.rowcount = 1

        failed = fail_command(
            command_id="command-1",
            error_message="MT5 order rejected"
        )

        self.assertTrue(failed)

    @patch("execution.command_queue.get_connection")
    def test_fail_command_returns_false_for_unknown_command(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.rowcount = 0

        failed = fail_command(
            command_id="unknown-command",
            error_message="MT5 order rejected"
        )

        self.assertFalse(failed)


if __name__ == "__main__":
    unittest.main()
