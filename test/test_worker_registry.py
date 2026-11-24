from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from worker_registry import WorkerRegistry


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def worker_registry(mock_db):
    return WorkerRegistry(db=mock_db)


def make_worker(
    worker_id: str,
    account_id: str,
    status: str = "online",
    active_connections: int = 0,
    last_seen: datetime | None = None,
) -> MagicMock:
    worker = MagicMock()

    worker.id = worker_id
    worker.account_id = account_id
    worker.status = status
    worker.active_connections = active_connections
    worker.max_connections = 1
    worker.last_seen = last_seen or datetime.now(timezone.utc)

    return worker


def test_register_worker_success(worker_registry, mock_db):
    mock_db.get_worker_by_id.return_value = None
    mock_db.create_worker.return_value = make_worker(
        worker_id="worker-1",
        account_id="account-1",
    )

    result = worker_registry.register_worker(
        worker_id="worker-1",
        account_id="account-1",
        worker_url="https://worker-1.example.com",
    )

    assert result["success"] is True
    assert result["message"] == "Worker registered successfully."
    assert result["worker_id"] == "worker-1"


def test_register_worker_rejects_duplicate(worker_registry, mock_db):
    mock_db.get_worker_by_id.return_value = make_worker(
        worker_id="worker-1",
        account_id="account-1",
    )

    result = worker_registry.register_worker(
        worker_id="worker-1",
        account_id="account-2",
        worker_url="https://worker-1.example.com",
    )

    assert result["success"] is False
    assert "already registered" in result["message"]


def test_assign_worker_rejects_when_no_workers(worker_registry, mock_db):
    mock_db.get_online_workers.return_value = []

    result = worker_registry.assign_worker(
        account_id="account-1",
    )

    assert result["success"] is False
    assert "No online workers available" in result["message"]


def test_assign_worker_rejects_when_capacity_full(worker_registry, mock_db):
    worker = make_worker(
        worker_id="worker-1",
        account_id="account-1",
        active_connections=1,
    )

    mock_db.get_online_workers.return_value = [worker]

    result = worker_registry.assign_worker(
        account_id="account-2",
    )

    assert result["success"] is False
    assert "No worker capacity available" in result["message"]


def test_assign_worker_skips_same_account(worker_registry, mock_db):
    worker = make_worker(
        worker_id="worker-1",
        account_id="account-1",
        active_connections=0,
    )

    mock_db.get_online_workers.return_value = [worker]

    result = worker_registry.assign_worker(
        account_id="account-1",
    )

    assert result["success"] is False
    assert "No worker capacity available" in result["message"]


def test_assign_worker_success(worker_registry, mock_db):
    worker = make_worker(
        worker_id="worker-1",
        account_id="account-1",
        active_connections=0,
    )

    mock_db.get_online_workers.return_value = [worker]
    mock_db.increment_worker_connections.return_value = True

    result = worker_registry.assign_worker(
        account_id="account-2",
    )

    assert result["success"] is True
    assert result["worker_id"] == "worker-1"
    assert result["worker_url"] == worker.worker_url


def test_release_worker_success(worker_registry, mock_db):
    mock_db.decrement_worker_connections.return_value = True

    result = worker_registry.release_worker(
        worker_id="worker-1",
    )

    assert result["success"] is True
    assert result["message"] == "Worker connection released."


def test_release_worker_failure(worker_registry, mock_db):
    mock_db.decrement_worker_connections.return_value = False

    result = worker_registry.release_worker(
        worker_id="worker-1",
    )

    assert result["success"] is False
    assert "Failed to release worker connection" in result["message"]


def test_get_worker_status(worker_registry, mock_db):
    worker = make_worker(
        worker_id="worker-1",
        account_id="account-1",
        status="online",
        active_connections=0,
    )

    mock_db.get_worker_by_id.return_value = worker

    result = worker_registry.get_worker_status(
        worker_id="worker-1",
    )

    assert result["success"] is True
    assert result["worker_id"] == "worker-1"
    assert result["status"] == "online"
    assert result["active_connections"] == 0


def test_get_worker_status_not_found(worker_registry, mock_db):
    mock_db.get_worker_by_id.return_value = None

    result = worker_registry.get_worker_status(
        worker_id="worker-1",
    )

    assert result["success"] is False
    assert "Worker not found" in result["message"]


def test_mark_worker_offline(worker_registry, mock_db):
    mock_db.update_worker_status.return_value = True

    result = worker_registry.mark_worker_offline(
        worker_id="worker-1",
    )

    assert result["success"] is True
    assert result["message"] == "Worker marked offline."


def test_mark_worker_offline_failure(worker_registry, mock_db):
    mock_db.update_worker_status.return_value = False

    result = worker_registry.mark_worker_offline(
        worker_id="worker-1",
    )

    assert result["success"] is False
    assert "Failed to mark worker offline" in result["message"]
