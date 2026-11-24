import os

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    text,
)

from database.models import (
    Account,
    Command,
    LicenseEntitlement,
    Session,
    Worker,
)


class MigrationRunner:
    """
    Creates the durable control-plane tables.

    Preserves the original Gold Scalper trading style.
    Does not change strategy, risk, entries, exits, or lot sizing.
    """

    def __init__(self, database):
        self.database = database

    def run(self) -> None:
        self.database.create_all()

        self._ensure_worker_columns()
        self._ensure_account_columns()
        self._ensure_command_columns()
        self._ensure_license_columns()
        self._ensure_session_columns()

    def _ensure_worker_columns(self) -> None:
        self._add_column_if_missing(
            Worker,
            "max_accounts",
            Integer,
            "10",
        )

        self._add_column_if_missing(
            Worker,
            "active_accounts",
            Integer,
            "0",
        )

        self._add_column_if_missing(
            Worker,
            "last_heartbeat_at",
            DateTime(timezone=True),
            None,
        )

    def _ensure_account_columns(self) -> None:
        self._add_column_if_missing(
            Account,
            "worker_id",
            String(64),
            None,
        )

        self._add_column_if_missing(
            Account,
            "connection_status",
            String(32),
            "DISCONNECTED",
        )

        self._add_column_if_missing(
            Account,
            "last_position_update_at",
            DateTime(timezone=True),
            None,
        )

        self._add_column_if_missing(
            Account,
            "last_seen_at",
            DateTime(timezone=True),
            None,
        )

    def _ensure_command_columns(self) -> None:
        self._add_column_if_missing(
            Command,
            "worker_id",
            String(64),
            None,
        )

        self._add_column_if_missing(
            Command,
            "attempts",
            Integer,
            "0",
        )

        self._add_column_if_missing(
            Command,
            "last_error",
            Text,
            None,
        )

        self._add_column_if_missing(
            Command,
            "completed_at",
            DateTime(timezone=True),
            None,
        )

    def _ensure_license_columns(self) -> None:
        self._add_column_if_missing(
            LicenseEntitlement,
            "payment_verified",
            Boolean,
            "0",
        )

        self._add_column_if_missing(
            LicenseEntitlement,
            "active",
            Boolean,
            "0",
        )

        self._add_column_if_missing(
            LicenseEntitlement,
            "expires_at",
            DateTime(timezone=True),
            None,
        )

    def _ensure_session_columns(self) -> None:
        self._add_column_if_missing(
            Session,
            "revoked",
            Boolean,
            "0",
        )

    def _add_column_if_missing(
        self,
        model,
        column_name: str,
        column_type,
        default_value: str | None,
    ) -> None:
        table_name = model.__tablename__
        column_type_name = self._sql_type_name(column_type)

        exists = self.database.session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = :table_name
                AND column_name = :column_name
                """
            ),
            {
                "table_name": table_name,
                "column_name": column_name,
            },
        ).fetchone()

        if exists:
            return

        default_sql = ""

        if default_value is not None:
            default_sql = f" DEFAULT {default_value}"

        self.database.session.execute(
            text(
                f"""
                ALTER TABLE {table_name}
                ADD COLUMN {column_name} {column_type_name}{default_sql}
                """
            )
        )

        self.database.session.commit()

    def _sql_type_name(self, column_type) -> str:
        if isinstance(column_type, String):
            return f"VARCHAR({column_type.length or 255})"

        if isinstance(column_type, Integer):
            return "INTEGER"

        if isinstance(column_type, Float):
            return "DOUBLE PRECISION"

        if isinstance(column_type, Boolean):
            return "BOOLEAN"

        if isinstance(column_type, DateTime):
            return "TIMESTAMPTZ"

        if isinstance(column_type, Text):
            return "TEXT"

        raise ValueError(
            f"Unsupported migration column type: {column_type}"
        )


def run_migrations(database) -> None:
    runner = MigrationRunner(database)
    runner.run()
