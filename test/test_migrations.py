import unittest
from unittest.mock import patch, MagicMock

from database.migrations import (
    run_migrations,
    get_required_tables
)


class TestMigrations(unittest.TestCase):
    def setUp(self):
        self.mock_connection = MagicMock()
        self.mock_cursor = MagicMock()

        self.mock_connection.cursor.return_value = (
            self.mock_cursor
        )

    def test_get_required_tables_returns_expected_tables(self):
        tables = get_required_tables()

        expected_tables = [
            "users",
            "accounts",
            "bot_sessions",
            "trade_commands",
            "worker_registry",
            "licenses"
        ]

        for table in expected_tables:
            self.assertIn(
                table,
                tables
            )

    @patch("database.migrations.get_connection")
    def test_run_migrations_executes_sql(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        run_migrations()

        self.mock_cursor.execute.assert_called()

    @patch("database.migrations.get_connection")
    def test_run_migrations_commits_changes(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        run_migrations()

        self.mock_connection.commit.assert_called_once()

    @patch("database.migrations.get_connection")
    def test_run_migrations_rolls_back_on_error(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.execute.side_effect = Exception(
            "Migration failed"
        )

        with self.assertRaises(Exception):
            run_migrations()

        self.mock_connection.rollback.assert_called_once()

    @patch("database.migrations.get_connection")
    def test_run_migrations_is_safe_to_run_twice(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        run_migrations()
        run_migrations()

        self.assertEqual(
            self.mock_connection.commit.call_count,
            2
        )


if __name__ == "__main__":
    unittest.main()
