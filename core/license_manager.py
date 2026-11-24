import os
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class LicenseCheckResult:
    recognized: bool
    trading_authorized: bool
    reason: str
    license_key: str | None = None


class LicenseManager:
    """
    Recognizes the original BossMode license keys.

    Important:
    Recognizing a license key does NOT authorize live trading.

    Live trading requires:
    - A valid verified entitlement from Bolt
    - A connected MT5 account
    - An active isolated MT5 worker
    - Explicit live-trading authorization
    """

    KNOWN_LICENSE_KEYS = {
        "BOSSMODE99",
        "BOSSMODE98",
        "BOSSMODE30D",
        "BOSSMODE01D",
    }

    def __init__(self, database):
        self.database = database

    def normalize_license_key(self, license_key: str | None) -> str:
        return str(license_key or "").strip().upper()

    def is_known_license_key(self, license_key: str | None) -> bool:
        normalized = self.normalize_license_key(license_key)

        return normalized in self.KNOWN_LICENSE_KEYS

    def check_license(
        self,
        license_key: str | None,
    ) -> LicenseCheckResult:
        normalized = self.normalize_license_key(license_key)

        if not normalized:
            return LicenseCheckResult(
                recognized=False,
                trading_authorized=False,
                reason="License key is missing.",
            )

        if not self.is_known_license_key(normalized):
            return LicenseCheckResult(
                recognized=False,
                trading_authorized=False,
                reason="License key is not recognized.",
                license_key=normalized,
            )

        entitlement = self.database.get_license_entitlement(normalized)

        if not entitlement:
            return LicenseCheckResult(
                recognized=True,
                trading_authorized=False,
                reason=(
                    "License key is recognized, but no verified "
                    "Bolt entitlement was found."
                ),
                license_key=normalized,
            )

        if not entitlement.get("payment_verified", False):
            return LicenseCheckResult(
                recognized=True,
                trading_authorized=False,
                reason="Bolt payment has not been verified.",
                license_key=normalized,
            )

        if not entitlement.get("active", False):
            return LicenseCheckResult(
                recognized=True,
                trading_authorized=False,
                reason="License entitlement is not active.",
                license_key=normalized,
            )

        expires_at = entitlement.get("expires_at")

        if expires_at:
            if isinstance(expires_at, str):
                try:
                    expires_at = datetime.fromisoformat(
                        expires_at.replace("Z", "+00:00")
                    )

                except Exception:
                    return LicenseCheckResult(
                        recognized=True,
                        trading_authorized=False,
                        reason="License expiry date is invalid.",
                        license_key=normalized,
                    )

            if expires_at <= datetime.now(timezone.utc):
                return LicenseCheckResult(
                    recognized=True,
                    trading_authorized=False,
                    reason="License entitlement has expired.",
                    license_key=normalized,
                )

        if not self._live_trading_enabled():
            return LicenseCheckResult(
                recognized=True,
                trading_authorized=False,
                reason=(
                    "License is valid, but live trading is disabled "
                    "until safety and execution tests are complete."
                ),
                license_key=normalized,
            )

        return LicenseCheckResult(
            recognized=True,
            trading_authorized=True,
            reason="License is recognized and live trading is authorized.",
            license_key=normalized,
        )

    def _live_trading_enabled(self) -> bool:
        return os.environ.get(
            "ENABLE_LIVE_TRADING",
            "false",
        ).strip().lower() == "true"
