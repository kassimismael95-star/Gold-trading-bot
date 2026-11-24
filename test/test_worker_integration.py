import unittest
from unittest.mock import patch, MagicMock

from worker.main import (
    validate_command,
    execute_command,
    process_command
)


class TestWorkerIntegration(unittest.TestCase):
    def setUp(self):
        self.valid_command = {
            "id": "command-1",
            "worker_id": "worker-1",
            "command_type": "OPEN_POSITION",
            "payload": {
                "symbol": "XAUUSD",
                "direction": "BUY",
                "volume": 0.01,
                "stop_loss": 2295.00,
                "take_profit": 2305.00
            }
        }

    def test_validate_command_accepts_valid_open_position(self):
        result = validate_command(
            command=self.valid_command
        )

        self.assertTrue(result)

    def test_validate_command_rejects_missing_command_id(self):
        command = self.valid_command.copy()
        command.pop("id")

        with self.assertRaises(ValueError):
            validate_command(command=command)

    def test_validate_command_rejects_missing_worker_id(self):
        command = self.valid_command.copy()
        command.pop("worker_id")

        with self.assertRaises(ValueError):
            validate_command(command=command)

    def test_validate_command_rejects_unknown_command_type(self):
        command = self.valid_command.copy()
        command["command_type"] = "UNKNOWN_COMMAND"

        with self.assertRaises(ValueError):
            validate_command(command=command)

    def test_validate_command_rejects_missing_payload(self):
        command = self.valid_command.copy()
        command.pop("payload")

        with self.assertRaises(ValueError):
            validate_command(command=command)

    @patch("worker.main.mt5")
    def test_execute_command_returns_success_for_open_position(
        self,
        mock_mt5
    ):
        mock_mt5.order_send.return_value = {
            "retcode": 10009,
            "order": 123456,
            "comment": "Order executed"
        }

        result = execute_command(
            command=self.valid_command
        )

        self.assertEqual(
            result["status"],
            "EXECUTED"
        )

        self.assertEqual(
            result["ticket"],
            123456
        )

    @patch("worker.main.mt5")
    def test_execute_command_returns_error_for_rejected_order(
        self,
        mock_mt5
    ):
        mock_mt5.order_send.return_value = {
            "retcode": 10015,
            "order": 0,
            "comment": "Invalid price"
        }

        result = execute_command(
            command=self.valid_command
        )

        self.assertEqual(
            result["status"],
            "REJECTED"
        )

        self.assertEqual(
            result["reason"],
            "Invalid price"
        )

    @patch("worker.main.mt5")
    def test_execute_command_returns_error_for_mt5_exception(
        self,
        mock_mt5
    ):
        mock_mt5.order_send.side_effect = Exception(
            "MT5 unavailable"
        )

        result = execute_command(
            command=self.valid_command
        )

        self.assertEqual(
            result["status"],
            "ERROR"
        )

        self.assertEqual(
            result["reason"],
            "MT5 unavailable"
        )

    @patch("worker.main.execute_command")
    def test_process_command_returns_completed_result(
        self,
        mock_execute_command
    ):
        mock_execute_command.return_value = {
            "status": "EXECUTED",
            "ticket": 123456
        }

        result = process_command(
            command=self.valid_command
        )

        self.assertEqual(
            result["status"],
            "COMPLETED"
        )

        self.assertEqual(
            result["result"]["ticket"],
            123456
        )

    @patch("worker.main.execute_command")
    def test_process_command_returns_failed_result(
        self,
        mock_execute_command
    ):
        mock_execute_command.return_value = {
            "status": "REJECTED",
            "reason": "Invalid price"
        }

        result = process_command(
            command=self.valid_command
        )

        self.assertEqual(
            result["status"],
            "FAILED"
        )

        self.assertEqual(
            result["error_message"],
            "Invalid price"
        )

    def test_process_command_rejects_invalid_command(self):
        command = self.valid_command.copy()
        command["command_type"] = "UNKNOWN_COMMAND"

        result = process_command(
            command=command
        )

        self.assertEqual(
            result["status"],
            "FAILED"
        )

        self.assertIn(
            "Invalid command",
            result["error_message"]
        )


if __name__ == "__main__":
    unittest.main()
