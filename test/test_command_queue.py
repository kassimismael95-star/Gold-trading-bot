import os
import unittest
from unittest.mock import patch

from execution.command_queue import (
    create_command,
    claim_next_command,
    mark_command_executing,
    mark_command_executed,
    mark_command_failed,
    get_command_status
)


class TestCommandQueue(unittest.TestCase):
    def setUp(self):
        self.test_user_id = 1
        self.test_account_id = 1
        self.test_bot_session_id = 1

    @patch("execution.command_queue.get_connection")
    def test_create_command_returns_command(self, mock_get_connection):
        mock_connection = mock_get_connection.return_value
        mock_cursor = mock_connection.cursor.return_value

        mock_cursor.fetchone.return_value = {
            "id": "test-command-id",
            "status": "PENDING"
        }

        command = create_command(
            user_id=self.test_user_id,
            account_id=self.test_account_id,
            bot_session_id=self.test_bot_session_id,
            command_type="OPEN_POSITION",
            symbol="XAUUSD",
            direction="BUY",
            volume=0.01,
            stop_loss=2300.00,
            take_profit=2302.20
        )

        self.assertEqual(
            command["id"],
            "test-command-id"
        )

        self.assertEqual(
            command["status"],
            "PENDING"
        )

    @patch("execution.command_queue.get_connection")
    def test_claim_next_command_returns_none_when_empty(
        self,
        mock_get_connection
    ):
        mock_connection = mock_get_connection.return_value
        mock_cursor = mock_connection.cursor.return_value

        mock_cursor.fetchone.return_value = None

        command = claim_next_command(
            worker_id="worker-1"
        )

        self.assertIsNone(command)

    @patch("execution.command_queue.get_connection")
    def test_mark_command_executing(self, mock_get_connection):
        mock_connection = mock_get_connection.return_value
        mock_cursor = mock_connection.cursor.return_value

        mock_cursor.rowcount = 1

        updated = mark_command_executing(
            command_id="test-command-id",
            worker_id="worker-1"
        )

        self.assertTrue(updated)

    @patch("execution.command_queue.get_connection")
    def test_mark_command_executed(self, mock_get_connection):
        mock_connection = mock_get_connection.return_value
        mock_cursor = mock_connection.cursor.return_value

        mock_cursor.rowcount = 1

        updated = mark_command_executed(
            command_id="test-command-id",
            result={"ticket": 123456}
        )

        self.assertTrue(updated)

    @patch("execution.command_queue.get_connection")
    def test_mark_command_failed(self, mock_get_connection):
        mock_connection = mock_get_connection.return_value
        mock_cursor = mock_connection.cursor.return_value

        mock_cursor.rowcount = 1

        updated = mark_command_failed(
            command_id="test-command-id",
            error_message="MT5 order rejected"
        )

        self.assertTrue(updated)

    @patch("execution.command_queue.get_connection")
    def test_get_command_status(self, mock_get_connection):
        mock_connection = mock_get_connection.return_value
        mock_cursor = mock_connection.cursor.return_value

        mock_cursor.fetchone.return_value = {
            "id": "test-command-id",
            "status": "EXECUTED"
        }

        command = get_command_status(
            user_id=self.test_user_id,
            command_id="test-command-id"
        )

        self.assertEqual(
            command["status"],
            "EXECUTED"
        )


if __name__ == "__main__":
    unittest.main()
