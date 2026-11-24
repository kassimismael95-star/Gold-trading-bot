import unittest
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
