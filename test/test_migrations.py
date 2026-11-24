from unittest.mock import MagicMock

import pytest

from database.migrations import MigrationRunner
from database.models import (
    Account,
    Command,
    LicenseEntitlement,
    Session,
    Worker,
)


@pytest.fixture
def database():
    database = MagicMock()

    database.session.execute.return_value.fetchone.return_value = None

    return database


@pytest.fixture
def migration_runner(database):
    return MigrationRunner(database=database)


def test_runner_creates_all_tables(migration_runner, database):
    migration_runner.run()

    database.create_all.assert_called_once()


def test_worker_columns_are_checked(migration_runner, database):
    migration_runner.run()

    executed_sql = " ".join(
        str(call.args[0])
        for call in database.session.execute.call_args_list
    )

    assert "max_accounts" in executed_sql
    assert "active_accounts" in executed_sql
    assert "last_heartbeat_at" in executed_sql


def test_account_columns_are_checked(migration_runner, database):
    migration_runner.run()

    executed_sql = " ".join(
        str(call.args[0])
        for call in database.session.execute.call_args_list
    )

    assert "worker_id" in executed_sql
    assert "connection_status" in executed_sql
    assert "last_position_update_at" in executed_sql
    assert "last_seen_at" in executed_sql


def test_command_columns_are_checked(migration_runner, database):
    migration_runner.run()

    executed_sql = " ".join(
        str(call.args[0])
        for call in database.session.execute.call_args_list
    )

    assert "worker_id" in executed_sql
    assert "attempts" in executed_sql
    assert "last_error" in executed_sql
    assert "completed_at" in executed_sql


def test_license_columns_are_checked(migration_runner, database):
    migration_runner.run()

    executed_sql = " ".join(
        str(call.args[0])
        for call in database.session.execute.call_args_list
    )

    assert "payment_verified" in executed_sql
    assert "active" in executed_sql
    assert "expires_at" in executed_sql


def test_session_columns_are_checked(migration_runner, database):
    migration_runner.run()

    executed_sql = " ".join(
        str(call.args[0])
        for call in database.session.execute.call_args_list
    )

    assert "revoked" in executed_sql


def test_existing_column_is_not_added_again(migration_runner, database):
    database.session.execute.return_value.fetchone.return_value = (1,)

    migration_runner._add_column_if_missing(
        model=Worker,
        column_name="max_accounts",
        column_type=__import__(
            "sqlalchemy",
            fromlist=["Integer"],
        ).Integer,
        default_value="10",
    )

    alter_calls = [
        call
        for call in database.session.execute.call_args_list
        if "ALTER TABLE" in str(call.args[0])
    ]

    assert len(alter_calls) == 0


def test_missing_column_is_added(migration_runner, database):
    database.session.execute.return_value.fetchone.return_value = None

    migration_runner._add_column_if_missing(
        model=Worker,
        column_name="max_accounts",
        column_type=__import__(
            "sqlalchemy",
            fromlist=["Integer"],
        ).Integer,
        default_value="10",
    )

    alter_calls = [
        call
        for call in database.session.execute.call_args_list
        if "ALTER TABLE" in str(call.args[0])
    ]

    assert len(alter_calls) == 1
    assert "ADD COLUMN max_accounts INTEGER DEFAULT 10" in str(
        alter_calls[0].args[0]
    )
