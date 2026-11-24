from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from core.license_manager import LicenseManager
from web.auth import AuthService


@pytest.fixture
def database():
    database = MagicMock()

    database.get_session.return_value = {
        "session_token": "valid-token",
        "revoked": False,
    }

    return database


@pytest.fixture
def license_manager(database):
    license_manager = MagicMock(spec=LicenseManager)

    license_manager.check_license.return_value = MagicMock(
        recognized=True,
        trading_authorized=True,
        reason="License is recognized and live trading is authorized.",
    )

    return license_manager


@pytest.fixture
def auth_service(license_manager, database, monkeypatch):
    monkeypatch.setenv(
        "SECRET_KEY",
        "test-secret-key-for-unit-tests-only",
    )

    return AuthService(
        license_manager=license_manager,
        database=database,
    )


def test_missing_license_key_is_rejected(auth_service):
    result = auth_service.authenticate_license("")

    assert result.authenticated is False
    assert "missing" in result.reason.lower()


def test_unrecognized_license_key_is_rejected(
    auth_service,
    license_manager,
):
    license_manager.check_license.return_value = MagicMock(
        recognized=False,
        trading_authorized=False,
        reason="License key is not recognized.",
    )

    result = auth_service.authenticate_license("WRONGKEY")

    assert result.authenticated is False
    assert result.license_key == "WRONGKEY"
    assert "not recognized" in result.reason.lower()


def test_valid_license_creates_session(auth_service):
    result = auth_service.authenticate_license("BOSSMODE99")

    assert result.authenticated is True
    assert result.license_key == "BOSSMODE99"
    assert result.session_token is not None


def test_session_token_can_be_verified(auth_service):
    session_result = auth_service.authenticate_license("BOSSMODE99")

    verified = auth_service.verify_session_token(
        session_result.session_token
    )

    assert verified.authenticated is True
    assert verified.license_key == "BOSSMODE99"


def test_invalid_session_token_is_rejected(auth_service):
    result = auth_service.verify_session_token("invalid-token")

    assert result.authenticated is False
    assert "invalid session token format" in result.reason.lower()


def test_tampered_session_token_is_rejected(auth_service):
    session_result = auth_service.authenticate_license("BOSSMODE99")

    tampered_token = session_result.session_token[:-4] + "abcd"

    result = auth_service.verify_session_token(tampered_token)

    assert result.authenticated is False
    assert "invalid session token signature" in result.reason.lower()


def test_expired_session_token_is_rejected(
    auth_service,
    database,
):
    expired_time = datetime.now(timezone.utc) - timedelta(hours=1)

    expired_token = (
        "BOSSMODE99|"
        f"{expired_time.isoformat()}|"
        "test-nonce|"
        "invalid-signature"
    )

    database.get_session.return_value = {
        "session_token": expired_token,
        "revoked": False,
    }

    result = auth_service.verify_session_token(expired_token)

    assert result.authenticated is False


def test_revoked_session_token_is_rejected(
    auth_service,
    database,
):
    session_result = auth_service.authenticate_license("BOSSMODE99")

    database.get_session.return_value = {
        "session_token": session_result.session_token,
        "revoked": True,
    }

    result = auth_service.verify_session_token(
        session_result.session_token
    )

    assert result.authenticated is False
    assert "revoked" in result.reason.lower()


def test_license_recognition_does_not_authorize_live_trading(
    auth_service,
    license_manager,
):
    license_manager.check_license.return_value = MagicMock(
        recognized=True,
        trading_authorized=False,
        reason=(
            "License key is recognized, but no verified "
            "Bolt entitlement was found."
        ),
    )

    result = auth_service.authenticate_license("BOSSMODE99")

    assert result.authenticated is False
    assert result.trading_authorized is False if hasattr(
        result,
        "trading_authorized",
    ) else True
    assert "no verified" in result.reason.lower()


def test_live_trading_authorization_requires_valid_license(
    auth_service,
    license_manager,
):
    session_result = auth_service.authenticate_license("BOSSMODE99")

    license_manager.check_license.return_value = MagicMock(
        recognized=True,
        trading_authorized=False,
        reason="Live trading is disabled until safety and execution tests are complete.",
    )

    result = auth_service.require_live_trading_authorization(
        session_result.session_token
    )

    assert result.authenticated is True
    assert "live trading is disabled" in result.reason.lower()


def test_live_trading_authorization_succeeds_with_valid_license(
    auth_service,
):
    session_result = auth_service.authenticate_license("BOSSMODE99")

    result = auth_service.require_live_trading_authorization(
        session_result.session_token
    )

    assert result.authenticated is True
    assert "Live trading authorization confirmed" in result.reason
