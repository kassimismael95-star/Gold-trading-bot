import unittest
from unittest.mock import patch, MagicMock

from execution.worker_registry import (
    register_worker,
    get_best_worker,
    update_worker_heartbeat,
    mark_worker_offline,
    list_workers
)


class TestWorkerRegistry(unittest.TestCase):
    def setUp(self):
        self.mock_connection = MagicMock()
        self.mock_cursor = MagicMock()

        self.mock_connection.cursor.return_value = (
            self.mock_cursor
        )

    @patch("execution.worker_registry.get_connection")
    def test_register_worker_returns_worker(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.fetchone.return_value = {
            "id": 1,
            "worker_id": "worker-1",
            "worker_status": "ONLINE",
            "current_load": 0
        }

        worker = register_worker(
            worker_id="worker-1",
            worker_name="Primary Worker",
            max_concurrent_commands=5
        )

        self.assertEqual(worker["worker_id"], "worker-1")
        self.assertEqual(worker["worker_status"], "ONLINE")
        self.assertEqual(worker["current_load"], 0)

    @patch("execution.worker_registry.get_connection")
    def test_get_best_worker_returns_least_loaded_worker(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.fetchone.return_value = {
            "worker_id": "worker-2",
            "worker_status": "ONLINE",
            "current_load": 1
        }

        worker = get_best_worker()

        self.assertEqual(worker["worker_id"], "worker-2")
        self.assertEqual(worker["current_load"], 1)

    @patch("execution.worker_registry.get_connection")
    def test_get_best_worker_returns_none_when_no_workers(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.fetchone.return_value = None

        worker = get_best_worker()

        self.assertIsNone(worker)

    @patch("execution.worker_registry.get_connection")
    def test_update_worker_heartbeat_returns_true(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.rowcount = 1

        updated = update_worker_heartbeat(
            worker_id="worker-1",
            current_load=2
        )

        self.assertTrue(updated)

    @patch("execution.worker_registry.get_connection")
    def test_update_worker_heartbeat_returns_false_for_unknown_worker(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.rowcount = 0

        updated = update_worker_heartbeat(
            worker_id="unknown-worker",
            current_load=0
        )

        self.assertFalse(updated)

    @patch("execution.worker_registry.get_connection")
    def test_mark_worker_offline_returns_true(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.rowcount = 1

        updated = mark_worker_offline(
            worker_id="worker-1"
        )

        self.assertTrue(updated)

    @patch("execution.worker_registry.get_connection")
    def test_mark_worker_offline_returns_false_for_unknown_worker(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.rowcount = 0

        updated = mark_worker_offline(
            worker_id="unknown-worker"
        )

        self.assertFalse(updated)

    @patch("execution.worker_registry.get_connection")
    def test_list_workers_returns_workers(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.fetchall.return_value = [
            {
                "worker_id": "worker-1",
                "worker_status": "ONLINE",
                "current_load": 0
            },
            {
                "worker_id": "worker-2",
                "worker_status": "OFFLINE",
                "current_load": 0
            }
        ]

        workers = list_workers()

        self.assertEqual(len(workers), 2)
        self.assertEqual(workers[0]["worker_id"], "worker-1")
        self.assertEqual(workers[1]["worker_status"], "OFFLINE")


if __name__ == "__main__":
    unittest.main()
