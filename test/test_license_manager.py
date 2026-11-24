from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from core.license_manager import LicenseManager


@pytest.fixture
def database():
    return MagicMock()


@pytest.fixture
def license_manager(database):
    return LicenseManager(database=database)


def test_recognizes_bossmode99(license_manager):
    result = license_manager.check_license("BOSSMODE99")

    assert result.recognized is True
    assert result.license_key == "BOSSMODE99"


def test_recognizes_bossmode98(license_manager):
    result = license_manager.check_license("BOSSMODE98")

    assert result.recognized is True
    assert result.license_key == "BOSSMODE98"


def test_recognizes_bossmode30d(license_manager):
    result = license_manager.check_license("BOSSMODE30D")

    assert result.recognized is True
    assert result.license_key == "BOSSMODE30D"


def test_recognizes_bossmode01d(license_manager):
    result = license_manager.check_license("BOSSMODE01D")

    assert result.recognized is True
    assert result.license_key == "BOSSMODE01D"


def test_rejects_unknown_license_key(license_manager):
    result = license_manager.check_license("WRONGKEY")

    assert result.recognized is False
    assert result.trading_authorized is False
    assert result.license_key == "WRONGKEY"


def test_rejects_missing_license_key(license_manager):
    result = license_manager.check_license("")

    assert result.recognized is False
    assert result.trading_authorized is False


def test_license_recognition_does_not_authorize_live_trading(
    license_manager,
    database,
):
    database.get_license_entitlement.return_value = None

    result = license_manager.check_license("BOSSMODE99")

    assert result.recognized is True
    assert result.trading_authorized is False
    assert "no verified" in result.reason.lower()


def test_unverified_payment_blocks_live_trading(
    license_manager,
    database,
):
    database.get_license_entitlement.return_value = {
        "payment_verified": False,
        "active": True,
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(days=30)
        ).isoformat(),
    }

    result = license_manager.check_license("BOSSMODE99")

    assert result.recognized is True
    assert result.trading_authorized is False
    assert "payment" in result.reason.lower()


def test_inactive_entitlement_blocks_live_trading(
    license_manager,
    database,
):
    database.get_license_entitlement.return_value = {
        "payment_verified": True,
        "active": False,
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(days=30)
        ).isoformat(),
    }

    result = license_manager.check_license("BOSSMODE99")

    assert result.recognized is True
    assert result.trading_authorized is False
    assert "not active" in result.reason.lower()


def test_expired_entitlement_blocks_live_trading(
    license_manager,
    database,
):
    database.get_license_entitlement.return_value = {
        "payment_verified": True,
        "active": True,
        "expires_at": (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat(),
    }

    result = license_manager.check_license("BOSSMODE99")

    assert result.recognized is True
    assert result.trading_authorized is False
    assert "expired" in result.reason.lower()


def test_live_trading_disabled_blocks_authorization(
    license_manager,
    database,
    monkeypatch,
):
    monkeypatch.setenv("ENABLE_LIVE_TRADING", "false")

    database.get_license_entitlement.return_value = {
        "payment_verified": True,
        "active": True,
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(days=30)
        ).isoformat(),
    }

    result = license_manager.check_license("BOSSMODE99")

    assert result.recognized is True
    assert result.trading_authorized is False
    assert "live trading is disabled" in result.reason.lower()


def test_valid_entitlement_and_live_trading_enabled_authorizes(
    license_manager,
    database,
    monkeypatch,
):
    monkeypatch.setenv("ENABLE_LIVE_TRADING", "true")

    database.get_license_entitlement.return_value = {
        "payment_verified": True,
        "active": True,
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(days=30)
        ).isoformat(),
    }

    result = license_manager.check_license("BOSSMODE99")

    assert result.recognized is True
    assert result.trading_authorized is True
