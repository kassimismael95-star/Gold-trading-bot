import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class AuthResult:
    authenticated: bool
    reason: str
    license_key: str | None = None
    session_token: str | None = None


class AuthService:
    """
    Secures the Gold Scalper control plane.

    Preserves the original license-key workflow:
    - BOSSMODE99
    - BOSSMODE98
    - BOSSMODE30D
    - BOSSMODE01D

    Adds:
    - Constant-time license comparison
    - Signed session tokens
    - Session expiry
    - Live-trading authorization separation
    """

    SESSION_DURATION_HOURS = 12

    def __init__(self, license_manager, database):
        self.license_manager = license_manager
        self.database = database

    def _secret_key(self) -> str:
        secret_key = os.environ.get("SECRET_KEY", "").strip()

        if not secret_key:
            raise ValueError(
                "SECRET_KEY is empty. "
                "Set it in the Render environment variables."
            )

        return secret_key

    def normalize_license_key(self, license_key: str | None) -> str:
        return str(license_key or "").strip().upper()

    def create_session_token(self, license_key: str) -> str:
        normalized = self.normalize_license_key(license_key)

        if not normalized:
            raise ValueError("License key is required to create a session.")

        expires_at = datetime.now(timezone.utc) + timedelta(
            hours=self.SESSION_DURATION_HOURS
        )

        nonce = secrets.token_urlsafe(32)

        payload = f"{normalized}|{expires_at.isoformat()}|{nonce}"

        signature = hmac.new(
            self._secret_key().encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        token = f"{payload}|{signature}"

        self.database.save_session(
            license_key=normalized,
            session_token=token,
            expires_at=expires_at,
        )

        return token

    def verify_session_token(self, session_token: str | None) -> AuthResult:
        if not session_token:
            return AuthResult(
                authenticated=False,
                reason="Session token is missing.",
            )

        parts = str(session_token).split("|")

        if len(parts) != 4:
            return AuthResult(
                authenticated=False,
                reason="Invalid session token format.",
            )

        license_key, expires_at_text, nonce, signature = parts

        payload = f"{license_key}|{expires_at_text}|{nonce}"

        expected_signature = hmac.new(
            self._secret_key().encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_signature):
            return AuthResult(
                authenticated=False,
                reason="Invalid session token signature.",
                license_key=self.normalize_license_key(license_key),
            )

        try:
            expires_at = datetime.fromisoformat(
                expires_at_text.replace("Z", "+00:00")
            )

        except Exception:
            return AuthResult(
                authenticated=False,
                reason="Invalid session expiry.",
                license_key=self.normalize_license_key(license_key),
            )

        if expires_at <= datetime.now(timezone.utc):
            return AuthResult(
                authenticated=False,
                reason="Session has expired.",
                license_key=self.normalize_license_key(license_key),
            )

        session = self.database.get_session(session_token)

        if not session:
            return AuthResult(
                authenticated=False,
                reason="Session was revoked or does not exist.",
                license_key=self.normalize_license_key(license_key),
            )

        return AuthResult(
            authenticated=True,
            reason="Session is valid.",
            license_key=self.normalize_license_key(license_key),
            session_token=session_token,
        )

    def authenticate_license(
        self,
        license_key: str | None,
    ) -> AuthResult:
        normalized = self.normalize_license_key(license_key)

        license_check = self.license_manager.check_license(normalized)

        if not license_check.recognized:
            return AuthResult(
                authenticated=False,
                reason=license_check.reason,
                license_key=normalized,
            )

        if not license_check.trading_authorized:
            return AuthResult(
                authenticated=False,
                reason=license_check.reason,
                license_key=normalized,
            )

        session_token = self.create_session_token(normalized)

        return AuthResult(
            authenticated=True,
            reason="License authenticated and session created.",
            license_key=normalized,
            session_token=session_token,
        )

    def require_live_trading_authorization(
        self,
        session_token: str | None,
    ) -> AuthResult:
        session_result = self.verify_session_token(session_token)

        if not session_result.authenticated:
            return session_result

        license_check = self.license_manager.check_license(
            session_result.license_key
        )

        if not license_check.trading_authorized:
            return AuthResult(
                authenticated=session_result.authenticated,
                reason=license_check.reason,
                license_key=session_result.license_key,
                session_token=session_result.session_token,
            )

        return AuthResult(
            authenticated=True,
            reason="Live trading authorization confirmed.",
            license_key=session_result.license_key,
            session_token=session_result.session_token,
        )
