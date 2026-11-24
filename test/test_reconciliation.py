import unittest
from unittest.mock import patch, MagicMock

from execution.reconciliation import (
    normalize_position,
    compare_positions,
    reconcile_account_positions
)


class TestReconciliation(unittest.TestCase):
    def setUp(self):
        self.mock_connection = MagicMock()
        self.mock_cursor = MagicMock()

        self.mock_connection.cursor.return_value = (
            self.mock_cursor
        )

    def test_normalize_position_extracts_required_fields(self):
        normalized = normalize_position(
            {
                "ticket": 123456,
                "symbol": "XAUUSD",
                "type": "BUY",
                "volume": 0.01,
                "price_open": 2300.00,
                "profit": 1.25
            }
        )

        self.assertEqual(
            normalized["ticket"],
            123456
        )

        self.assertEqual(
            normalized["symbol"],
            "XAUUSD"
        )

        self.assertEqual(
            normalized["direction"],
            "BUY"
        )

        self.assertEqual(
            normalized["volume"],
            0.01
        )

        self.assertEqual(
            normalized["entry_price"],
            2300.00
        )

        self.assertEqual(
            normalized["profit"],
            1.25
        )

    def test_compare_positions_returns_no_mismatch_when_equal(self):
        expected_positions = [
            {
                "ticket": 123456,
                "symbol": "XAUUSD",
                "direction": "BUY",
                "volume": 0.01,
                "entry_price": 2300.00,
                "profit": 1.00
            }
        ]

        worker_positions = [
            {
                "ticket": 123456,
                "symbol": "XAUUSD",
                "type": "BUY",
                "volume": 0.01,
                "price_open": 2300.00,
                "profit": 1.00
            }
        ]

        result = compare_positions(
            expected_positions=expected_positions,
            worker_positions=worker_positions
        )

        self.assertEqual(
            result["status"],
            "MATCHED"
        )

        self.assertEqual(
            len(result["mismatches"]),
            0
        )

    def test_compare_positions_detects_missing_worker_position(self):
        expected_positions = [
            {
                "ticket": 123456,
                "symbol": "XAUUSD",
                "direction": "BUY",
                "volume": 0.01,
                "entry_price": 2300.00,
                "profit": 1.00
            }
        ]

        worker_positions = []

        result = compare_positions(
            expected_positions=expected_positions,
            worker_positions=worker_positions
        )

        self.assertEqual(
            result["status"],
            "MISMATCH"
        )

        self.assertEqual(
            len(result["mismatches"]),
            1
        )

        self.assertEqual(
            result["mismatches"][0]["type"],
            "MISSING_ON_WORKER"
        )

    def test_compare_positions_detects_unexpected_worker_position(self):
        expected_positions = []

        worker_positions = [
            {
                "ticket": 789012,
                "symbol": "XAUUSD",
                "type": "SELL",
                "volume": 0.01,
                "price_open": 2300.00,
                "profit": -0.50
            }
        ]

        result = compare_positions(
            expected_positions=expected_positions,
            worker_positions=worker_positions
        )

        self.assertEqual(
            result["status"],
            "MISMATCH"
        )

        self.assertEqual(
            len(result["mismatches"]),
            1
        )

        self.assertEqual(
            result["mismatches"][0]["type"],
            "UNEXPECTED_ON_WORKER"
        )

    def test_compare_positions_detects_volume_mismatch(self):
        expected_positions = [
            {
                "ticket": 123456,
                "symbol": "XAUUSD",
                "direction": "BUY",
                "volume": 0.01,
                "entry_price": 2300.00,
                "profit": 1.00
            }
        ]

        worker_positions = [
            {
                "ticket": 123456,
                "symbol": "XAUUSD",
                "type": "BUY",
                "volume": 0.02,
                "price_open": 2300.00,
                "profit": 1.00
            }
        ]

        result = compare_positions(
            expected_positions=expected_positions,
            worker_positions=worker_positions
        )

        self.assertEqual(
            result["status"],
            "MISMATCH"
        )

        self.assertEqual(
            result["mismatches"][0]["type"],
            "VOLUME_MISMATCH"
        )

    @patch("execution.reconciliation.get_connection")
    @patch("execution.reconciliation.get_worker_positions")
    def test_reconcile_account_positions_returns_matched(
        self,
        mock_get_worker_positions,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.fetchall.return_value = [
            {
                "ticket": 123456,
                "symbol": "XAUUSD",
                "direction": "BUY",
                "volume": 0.01,
                "entry_price": 2300.00,
                "profit": 1.00
            }
        ]

        mock_get_worker_positions.return_value = [
            {
                "ticket": 123456,
                "symbol": "XAUUSD",
                "type": "BUY",
                "volume": 0.01,
                "price_open": 2300.00,
                "profit": 1.00
            }
        ]

        result = reconcile_account_positions(
            account_id=1,
            worker_id="worker-1"
        )

        self.assertEqual(
            result["status"],
            "MATCHED"
        )

        self.assertEqual(
            len(result["mismatches"]),
            0
        )

    @patch("execution.reconciliation.get_connection")
    @patch("execution.reconciliation.get_worker_positions")
    def test_reconcile_account_positions_returns_mismatch(
        self,
        mock_get_worker_positions,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.fetchall.return_value = [
            {
                "ticket": 123456,
                "symbol": "XAUUSD",
                "direction": "BUY",
                "volume": 0.01,
                "entry_price": 2300.00,
                "profit": 1.00
            }
        ]

        mock_get_worker_positions.return_value = []

        result = reconcile_account_positions(
            account_id=1,
            worker_id="worker-1"
        )

        self.assertEqual(
            result["status"],
            "MISMATCH"
        )

        self.assertEqual(
            len(result["mismatches"]),
            1
        )

    @patch("execution.reconciliation.get_connection")
    @patch("execution.reconciliation.get_worker_positions")
    def test_reconcile_account_positions_handles_worker_error(
        self,
        mock_get_worker_positions,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        mock_get_worker_positions.side_effect = Exception(
            "Worker unavailable"
        )

        result = reconcile_account_positions(
            account_id=1,
            worker_id="worker-1"
        )

        self.assertEqual(
            result["status"],
            "ERROR"
        )

        self.assertEqual(
            result["reason"],
            "Worker unavailable"
        )


if __name__ == "__main__":
    unittest.main()import unittest
from unittest.mock import patch

from execution.reconciliation import (
    compare_positions,
    is_position_safe_to_resume,
    reconcile_after_reconnect
)


class TestReconciliation(unittest.TestCase):
    def test_compare_positions_finds_missing_database_position(self):
        database_positions = [
            {
                "ticket": 101
            }
        ]

        broker_positions = [
            {
                "ticket": 101
            },
            {
                "ticket": 102
            }
        ]

        result = compare_positions(
            database_positions,
            broker_positions
        )

        self.assertEqual(
            result["missing_in_database"],
            [102]
        )

        self.assertEqual(
            result["missing_in_broker"],
            []
        )

        self.assertIn(101, result["matched_tickets"])

    def test_compare_positions_finds_missing_broker_position(self):
        database_positions = [
            {
                "ticket": 101
            },
            {
                "ticket": 103
            }
        ]

        broker_positions = [
            {
                "ticket": 101
            }
        ]

        result = compare_positions(
            database_positions,
            broker_positions
        )

        self.assertEqual(
            result["missing_in_database"],
            []
        )

        self.assertEqual(
            result["missing_in_broker"],
            [103]
        )

        self.assertIn(101, result["matched_tickets"])

    def test_compare_positions_handles_empty_lists(self):
        result = compare_positions(
            [],
            []
        )

        self.assertEqual(
            result["missing_in_database"],
            []
        )

        self.assertEqual(
            result["missing_in_broker"],
            []
        )

        self.assertEqual(
            result["matched_tickets"],
            []
        )

    def test_position_is_safe_to_resume(self):
        broker_position = {
            "ticket": 101,
            "symbol": "XAUUSD",
            "type": "BUY"
        }

        safe = is_position_safe_to_resume(
            broker_position=broker_position,
            expected_direction="BUY",
            expected_symbol="XAUUSD"
        )

        self.assertTrue(safe)

    def test_position_is_not_safe_with_wrong_direction(self):
        broker_position = {
            "ticket": 101,
            "symbol": "XAUUSD",
            "type": "SELL"
        }

        safe = is_position_safe_to_resume(
            broker_position=broker_position,
            expected_direction="BUY",
            expected_symbol="XAUUSD"
        )

        self.assertFalse(safe)

    def test_position_is_not_safe_with_wrong_symbol(self):
        broker_position = {
            "ticket": 101,
            "symbol": "EURUSD",
            "type": "BUY"
        }

        safe = is_position_safe_to_resume(
            broker_position=broker_position,
            expected_direction="BUY",
            expected_symbol="XAUUSD"
        )

        self.assertFalse(safe)

    def test_missing_position_is_not_safe_to_resume(self):
        safe = is_position_safe_to_resume(
            broker_position=None,
            expected_direction="BUY",
            expected_symbol="XAUUSD"
        )

        self.assertFalse(safe)

    @patch("execution.reconciliation.create_reconciliation_record")
    def test_reconcile_after_reconnect_records_mismatches(
        self,
        mock_create_record
    ):
        mock_create_record.return_value = 1

        database_positions = [
            {
                "ticket": 101
            }
        ]

        broker_positions = [
            {
                "ticket": 101
            },
            {
                "ticket": 102
            }
        ]

        result = reconcile_after_reconnect(
            user_id=1,
            account_id=1,
            bot_session_id=1,
            database_positions=database_positions,
            broker_positions=broker_positions
        )

        self.assertEqual(
            result["missing_in_database"],
            [102]
        )

        mock_create_record.assert_called_once()


if __name__ == "__main__":
    unittest.main()
