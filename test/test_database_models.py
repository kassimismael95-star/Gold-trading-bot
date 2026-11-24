import unittest

from database.models import (
    User,
    Account,
    BotSession,
    TradeCommand,
    WorkerRegistry,
    License
)


class TestDatabaseModels(unittest.TestCase):
    def test_user_table_name(self):
        self.assertEqual(
            User.__tablename__,
            "users"
        )

    def test_user_has_expected_columns(self):
        columns = User.__table__.columns.keys()

        expected_columns = [
            "id",
            "email",
            "password_hash",
            "created_at"
        ]

        for column in expected_columns:
            self.assertIn(
                column,
                columns
            )

    def test_account_table_name(self):
        self.assertEqual(
            Account.__tablename__,
            "accounts"
        )

    def test_account_has_expected_columns(self):
        columns = Account.__table__.columns.keys()

        expected_columns = [
            "id",
            "user_id",
            "broker_name",
            "login",
            "encrypted_password",
            "server_name",
            "status",
            "created_at"
        ]

        for column in expected_columns:
            self.assertIn(
                column,
                columns
            )

    def test_bot_session_table_name(self):
        self.assertEqual(
            BotSession.__tablename__,
            "bot_sessions"
        )

    def test_bot_session_has_expected_columns(self):
        columns = BotSession.__table__.columns.keys()

        expected_columns = [
            "id",
            "user_id",
            "account_id",
            "symbol",
            "risk_percent",
            "max_positions",
            "basket_target",
            "status",
            "created_at"
        ]

        for column in expected_columns:
            self.assertIn(
                column,
                columns
            )

    def test_trade_command_table_name(self):
        self.assertEqual(
            TradeCommand.__tablename__,
            "trade_commands"
        )

    def test_trade_command_has_expected_columns(self):
        columns = TradeCommand.__table__.columns.keys()

        expected_columns = [
            "id",
            "user_id",
            "account_id",
            "bot_session_id",
            "worker_id",
            "command_type",
            "payload",
            "status",
            "result",
            "error_message",
            "created_at",
            "updated_at"
        ]

        for column in expected_columns:
            self.assertIn(
                column,
                columns
            )

    def test_worker_registry_table_name(self):
        self.assertEqual(
            WorkerRegistry.__tablename__,
            "worker_registry"
        )

    def test_worker_registry_has_expected_columns(self):
        columns = WorkerRegistry.__table__.columns.keys()

        expected_columns = [
            "id",
            "worker_id",
            "worker_name",
            "worker_api_url",
            "worker_status",
            "max_concurrent_commands",
            "current_load",
            "last_heartbeat",
            "created_at"
        ]

        for column in expected_columns:
            self.assertIn(
                column,
                columns
            )

    def test_license_table_name(self):
        self.assertEqual(
            License.__tablename__,
            "licenses"
        )

    def test_license_has_expected_columns(self):
        columns = License.__table__.columns.keys()

        expected_columns = [
            "id",
            "user_id",
            "license_key",
            "status",
            "activated_at",
            "expires_at",
            "created_at"
        ]

        for column in expected_columns:
            self.assertIn(
                column,
                columns
            )


if __name__ == "__main__":
    unittest.main()
