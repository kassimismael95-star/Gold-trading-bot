from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from models import (
    Account,
    Command,
    License,
    Order,
    ReconciliationEvent,
    User,
    Worker,
)


@pytest.fixture
def mock_db():
    return MagicMock()


def make_user() -> User:
    return User(
        email="user@example.com",
        password_hash="hashed-password",
        is_active=True,
    )


def make_account() -> Account:
    return Account(
        user_id=1,
        account_name="Gold Scalper Account",
        broker_name="Exness",
        account_number="123456",
        server_name="Exness-MT5Real",
        account_type="real",
        is_active=True,
    )


def make_worker() -> Worker:
    return Worker(
        worker_id="worker-1",
        account_id=1,
        worker_url="https://worker-1.example.com",
        status="online",
        active_connections=0,
        max_connections=1,
    )


def make_command() -> Command:
    return Command(
        account_id=1,
        worker_id="worker-1",
        command_type="BUY",
        symbol="XAUUSDm",
        volume=0.01,
        stop_loss=3297.00,
        take_profit=3303.00,
        comment="BALANCED-SCALP-1 [BOSSMODE99]",
        status="pending",
    )


def make_order() -> Order:
    return Order(
        account_id=1,
        worker_id="worker-1",
        command_id=1,
        order_ticket=123456,
        deal_ticket=789012,
        symbol="XAUUSDm",
        direction="BUY",
        volume=0.01,
        entry_price=3300.10,
        stop_loss=3297.00,
        take_profit=3303.00,
        status="open",
        comment="BALANCED-SCALP-1 [BOSSMODE99]",
    )


def make_license() -> License:
    return License(
        license_key="BOSSMODE99",
        account_id=1,
        status="active",
        expires_at=datetime.now(timezone.utc),
    )


def make_reconciliation_event() -> ReconciliationEvent:
    return ReconciliationEvent(
        account_id=1,
        worker_id="worker-1",
        event_type="orphaned_position",
        ticket=123456,
        symbol="XAUUSDm",
        direction="BUY",
        volume=0.01,
        status="detected",
    )


def test_user_model_fields():
    user = make_user()

    assert user.email == "user@example.com"
    assert user.password_hash == "hashed-password"
    assert user.is_active is True


def test_account_model_fields():
    account = make_account()

    assert account.user_id == 1
    assert account.account_name == "Gold Scalper Account"
    assert account.broker_name == "Exness"
    assert account.account_number == "123456"
    assert account.server_name == "Exness-MT5Real"
    assert account.account_type == "real"
    assert account.is_active is True


def test_worker_model_fields():
    worker = make_worker()

    assert worker.worker_id == "worker-1"
    assert worker.account_id == 1
    assert worker.worker_url == "https://worker-1.example.com"
    assert worker.status == "online"
    assert worker.active_connections == 0
    assert worker.max_connections == 1


def test_command_model_fields():
    command = make_command()

    assert command.account_id == 1
    assert command.worker_id == "worker-1"
    assert command.command_type == "BUY"
    assert command.symbol == "XAUUSDm"
    assert command.volume == 0.01
    assert command.stop_loss == 3297.00
    assert command.take_profit == 3303.00
    assert command.comment == "BALANCED-SCALP-1 [BOSSMODE99]"
    assert command.status == "pending"


def test_order_model_fields():
    order = make_order()

    assert order.account_id == 1
    assert order.worker_id == "worker-1"
    assert order.command_id == 1
    assert order.order_ticket == 123456
    assert order.deal_ticket == 789012
    assert order.symbol == "XAUUSDm"
    assert order.direction == "BUY"
    assert order.volume == 0.01
    assert order.entry_price == 3300.10
    assert order.stop_loss == 3297.00
    assert order.take_profit == 3303.00
    assert order.status == "open"
    assert order.comment == "BALANCED-SCALP-1 [BOSSMODE99]"


def test_license_model_fields():
    license_record = make_license()

    assert license_record.license_key == "BOSSMODE99"
    assert license_record.account_id == 1
    assert license_record.status == "active"


def test_reconciliation_event_model_fields():
    event = make_reconciliation_event()

    assert event.account_id == 1
    assert event.worker_id == "worker-1"
    assert event.event_type == "orphaned_position"
    assert event.ticket == 123456
    assert event.symbol == "XAUUSDm"
    assert event.direction == "BUY"
    assert event.volume == 0.01
    assert event.status == "detected"


def test_command_status_transitions():
    command = make_command()

    assert command.status == "pending"

    command.status = "executing"
    assert command.status == "executing"

    command.status = "completed"
    assert command.status == "completed"

    command.status = "failed"
    assert command.status == "failed"


def test_order_status_transitions():
    order = make_order()

    assert order.status == "open"

    order.status = "closed"
    assert order.status == "closed"

    order.status = "failed"
    assert order.status == "failed"


def test_worker_status_transitions():
    worker = make_worker()

    assert worker.status == "online"

    worker.status = "offline"
    assert worker.status == "offline"

    worker.status = "busy"
    assert worker.status == "busy"
