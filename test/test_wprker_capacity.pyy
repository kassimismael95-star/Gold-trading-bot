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
    active_connections: int = 0,
    max_connections: int = 1,
    status: str = "online",
) -> MagicMock:
    worker = MagicMock()

    worker.id = worker_id
    worker.account_id = account_id
    worker.worker_url = f"https://{worker_id}.example.com"
    worker.status = status
    worker.active_connections = active_connections
    worker.max_connections = max_connections

    return worker


def test_rejects_assignment_when_no_workers_online(
    worker_registry,
    mock_db,
):
    mock_db.get_online_workers.return_value = []

    result = worker_registry.assign_worker(
        account_id="account-1",
    )

    assert result["success"] is False
    assert "No online workers available" in result["message"]


def test_rejects_assignment_when_all_workers_full(
    worker_registry,
    mock_db,
):
    worker_1 = make_worker(
        worker_id="worker-1",
        account_id="account-1",
        active_connections=1,
        max_connections=1,
    )

    worker_2 = make_worker(
        worker_id="worker-2",
        account_id="account-2",
        active_connections=1,
        max_connections=1,
    )

    mock_db.get_online_workers.return_value = [
        worker_1,
        worker_2,
    ]

    result = worker_registry.assign_worker(
        account_id="account-3",
    )

    assert result["success"] is False
    assert "No worker capacity available" in result["message"]


def test_rejects_assignment_when_worker_already_has_account(
    worker_registry,
    mock_db,
):
    worker = make_worker(
        worker_id="worker-1",
        account_id="account-1",
        active_connections=0,
        max_connections=1,
    )

    mock_db.get_online_workers.return_value = [worker]

    result = worker_registry.assign_worker(
        account_id="account-1",
    )

    assert result["success"] is False
    assert "No worker capacity available" in result["message"]


def test_assigns_worker_with_available_capacity(
    worker_registry,
    mock_db,
):
    worker = make_worker(
        worker_id="worker-1",
        account_id="account-1",
        active_connections=0,
        max_connections=1,
    )

    mock_db.get_online_workers.return_value = [worker]
    mock_db.increment_worker_connections.return_value = True

    result = worker_registry.assign_worker(
        account_id="account-2",
    )

    assert result["success"] is True
    assert result["worker_id"] == "worker-1"
    assert result["worker_url"] == worker.worker_url


def test_assigns_first_worker_with_capacity(
    worker_registry,
    mock_db,
):
    worker_1 = make_worker(
        worker_id="worker-1",
        account_id="account-1",
        active_connections=1,
        max_connections=1,
    )

    worker_2 = make_worker(
        worker_id="worker-2",
        account_id="account-2",
        active_connections=0,
        max_connections=1,
    )

    mock_db.get_online_workers.return_value = [
        worker_1,
        worker_2,
    ]

    mock_db.increment_worker_connections.return_value = True

    result = worker_registry.assign_worker(
        account_id="account-3",
    )

    assert result["success"] is True
    assert result["worker_id"] == "worker-2"
    assert result["worker_url"] == worker_2.worker_url


def test_release_worker_increases_available_capacity(
    worker_registry,
    mock_db,
):
    mock_db.decrement_worker_connections.return_value = True

    result = worker_registry.release_worker(
        worker_id="worker-1",
    )

    assert result["success"] is True
    assert result["message"] == "Worker connection released."


def test_release_worker_failure(
    worker_registry,
    mock_db,
):
    mock_db.decrement_worker_connections.return_value = False

    result = worker_registry.release_worker(
        worker_id="worker-1",
    )

    assert result["success"] is False
    assert "Failed to release worker connection" in result["message"]


def test_worker_capacity_is_backend_enforced(
    worker_registry,
    mock_db,
):
    worker = make_worker(
        worker_id="worker-1",
        account_id="account-1",
        active_connections=1,
        max_connections=1,
    )

    mock_db.get_online_workers.return_value = [worker]

    result = worker_registry.assign_worker(
        account_id="account-2",
    )

    assert result["success"] is False
    assert "No worker capacity available" in result["message"]


def test_worker_capacity_supports_multiple_connections(
    worker_registry,
    mock_db,
):
    worker = make_worker(
        worker_id="worker-1",
        account_id="account-1",
        active_connections=0,
        max_connections=3,
    )

    mock_db.get_online_workers.return_value = [worker]
    mock_db.increment_worker_connections.return_value = True

    result = worker_regi
