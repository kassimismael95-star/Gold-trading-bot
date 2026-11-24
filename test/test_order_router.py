import os
import unittest
from unittest.mock import patch, MagicMock

from execution.order_router import (
    get_worker_api_url,
    send_command_to_worker,
    route_command_to_worker
)


class TestOrderRouter(unittest.TestCase):
    def setUp(self):
        self.worker_id = "worker-1"
        self.command_id = "command-1"
        self.user_id = 1
        self.account_id = 1
        self.bot_session_id = 1

    @patch("execution.order_router.get_connection")
    def test_get_worker_api_url_requires_online_worker(
        self,
        mock_get_connection
    ):
        mock_connection = mock_get_connection.return_value
        mock_cursor = mock_connection.cursor.return_value

        mock_cursor.fetchone.return_value = {
            "worker_id": self.worker_id
        }

        with patch.dict(
            os.environ,
            {
                "WORKER_API_URL": "https://worker.example.com",
                "WORKER_SHARED_SECRET": "test-secret"
            }
        ):
            worker_url = get_worker_api_url(self.worker_id)

            self.assertEqual(
                worker_url,
                "https://worker.example.com"
            )

    @patch("execution.order_router.get_connection")
    def test_get_worker_api_url_rejects_offline_worker(
        self,
        mock_get_connection
    ):
        mock_connection = mock_get_connection.return_value
        mock_cursor = mock_connection.cursor.return_value

        mock_cursor.fetchone.return_value = None

        with self.assertRaises(ValueError):
            get_worker_api_url(self.worker_id)

    @patch("execution.order_router.requests.post")
    def test_send_command_to_worker_sends_authorization(
        self,
        mock_post
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "EXECUTED"
        }

        mock_post.return_value = mock_response

        with patch.dict(
            os.environ,
            {
                "WORKER_API_URL": "https://worker.example.com",
                "WORKER_SHARED_SECRET": "test-secret"
            }
        ):
            result = send_command_to_worker(
                self.worker_id,
                {
                    "command_id": self.command_id
                }
            )

            self.assertEqual(
                result["status"],
                "EXECUTED"
            )

        mock_post.assert_called_once()

        called_args = mock_post.call_args

        self.assertEqual(
            called_args.args[0],
            "https://worker.example.com/execute-command"
        )

        self.assertEqual(
            called_args.kwargs["headers"]["Authorization"],
            "Bearer test-secret"
        )

    @patch("execution.order_router.send_command_to_worker")
    def test_route_command_to_worker_builds_complete_command(
        self,
        mock_send_command
    ):
        mock_send_command.return_value = {
            "status": "EXECUTED"
        }

        result = route_command_to_worker(
            worker_id=self.worker_id,
            command_id=self.command_id,
            user_id=self.user_id,
            account_id=self.account_id,
            bot_session_id=self.bot_session_id,
            command_type="OPEN_POSITION",
            symbol="XAUUSD",
            direction="BUY",
            volume=0.01,
            stop_loss=2300.00,
            take_profit=2302.20
        )

        self.assertEqual(
            result["status"],
            "EXECUTED"
        )

        sent_command = mock_send_command.call_args.args[1]

        self.assertEqual(
            sent_command["command_id"],
            self.command_id
        )

        self.assertEqual(
            sent_command["user_id"],
            self.user_id
        )

        self.assertEqual(
            sent_command["account_id"],
            self.account_id
        )

        self.assertEqual(
            sent_command["bot_session_id"],
            self.bot_session_id
        )

        self.assertEqual(
            sent_command["symbol"],
            "XAUUSD"
        )

        self.assertEqual(
            sent_command["direction"],
            "BUY"
        )

        self.assertEqual(
            sent_command["volume"],
            0.01
        )

        self.assertEqual(
            sent_command["stop_loss"],
            2300.00
        )

        self.assertEqual(
            sent_command["take_profit"],
            2302.20
        )


if __name__ == "__main__":
    unittest.main()
