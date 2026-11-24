from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from license_auth import LicenseAuth


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def license_auth(mock_db):
    return LicenseAuth(db=mock_db)


def make_license(
    license_key: str,
    account_id: str = "account-1",
    status: str = "active",
    expires_at: datetime | None = None,
) -> MagicMock:
    license_record = MagicMock()

    license_record.license_key = license_key
    license_record.account_id = account_id
    license_record.status = status
    license_record.expires_at = (
        expires_at
        or datetime.now(timezone.utc) + timedelta(days=30)
    )

    return license_record


def test_valid_license_key_is_accepted(license_auth, mock_db):
    mock_db.get_license_by_key.return_value = make_license(
        license_key="BOSSMODE99",
    )

    result = license_auth.validate_license(
        license_key="BOSSMODE99",
        account_id="account-1",
    )

    assert result["success"] is True
    assert result["message"] == "License is valid."
    assert result["license_key"] == "BOSSMODE99"


def test_invalid_license_key_is_rejected(license_auth, mock_db):
    mock_db.get_license_by_key.return_value = None

    result = license_auth.validate_license(
        license_key="INVALID-KEY",
        account_id="account-1",
    )

    assert result["success"] is False
    assert "Invalid license key" in result["message"]


def test_license_bound_to_different_account_is_rejected(
    license_auth,
    mock_db,
):
    mock_db.get_license_by_key.return_value = make_license(
        license_key="BOSSMODE99",
        account_id="account-2",
    )

    result = license_auth.validate_license(
        license_key="BOSSMODE99",
        account_id="account-1",
    )

    assert result["success"] is False
    assert "License is bound to another account" in result["message"]


def test_expired_license_is_rejected(license_auth, mock_db):
    expired_license = make_license(
        license_key="BOSSMODE99",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    mock_db.get_license_by_key.return_value = expired_license

    result = license_auth.validate_license(
        license_key="BOSSMODE99",
        account_id="account-1",
    )

    assert result["success"] is False
    assert "License has expired" in result["message"]


def test_inactive_license_is_rejected(license_auth, mock_db):
    mock_db.get_license_by_key.return_value = make_license(
        license_key="BOSSMODE99",
        status="inactive",
    )

    result = license_auth.validate_license(
        license_key="BOSSMODE99",
        account_id="account-1",
    )

    assert result["success"] is False
    assert "License is inactive" in result["message"]


def test_bossmode98_license_is_valid(license_auth, mock_db):
    mock_db.get_license_by_key.return_value = make_license(
        license_key="BOSSMODE98",
    )

    result = license_auth.validate_license(
        license_key="BOSSMODE98",
        account_id="account-1",
    )

    assert result["success"] is True
    assert result["license_key"] == "BOSSMODE98"


def test_bossmode30d_license_is_valid(license_auth, mock_db):
    mock_db.get_license_by_key.return_value = make_license(
        license_key="BOSSMODE30D",
    )

    result = license_auth.validate_license(
        license_key="BOSSMODE30D",
        account_id="account-1",
    )

    assert result["success"] is True
    assert result["license_key"] == "BOSSMODE30D"


def test_bossmode01d_license_is_valid(license_auth, mock_db):
    mock_db.get_license_by_key.return_value = make_license(
        license_key="BOSSMODE01D",
    )

    result = license_auth.validate_license(
        license_key="BOSSMODE01D",
        account_id="account-1",
    )

    assert result["success"] is True
    assert result["license_key"] == "BOSSMODE01D"


def test_license_key_is_case_sensitive(license_auth, mock_db):
    mock_db.get_license_by_key.return_value = None

    result = license_auth.validate_license(
        license_key="bossmode99",
        account_id="account-1",
    )

    assert result["success"] is False
    assert "Invalid license key" in result["message"]
