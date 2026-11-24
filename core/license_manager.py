"""
Recognize supported license keys.

This module does not process payments, calculate expiry,
or prove that a license belongs to a user.
"""

import os


SUPPORTED_LICENSES = frozenset({
    "BOSSMODE99",
    "BOSSMODE98",
    "BOSSMODE30D",
    "BOSSMODE01D",
})


class LicenseConfigurationError(RuntimeError):
    """Raised when ALLOWED_LICENSES contains unsupported keys."""


def get_allowed_licenses():
    """
    Return the configured subset of supported keys.

    If ALLOWED_LICENSES is absent, recognize all four supported
    keys. An explicitly empty value disables all keys.
    """
    configured = os.environ.get("ALLOWED_LICENSES")

    if configured is None:
        return SUPPORTED_LICENSES

    allowed = frozenset(
        key.strip()
        for key in configured.split(",")
        if key.strip()
    )

    if allowed - SUPPORTED_LICENSES:
        raise LicenseConfigurationError(
            "ALLOWED_LICENSES contains unsupported license keys."
        )

    return allowed


def normalize_license_key(license_key):
    """Remove surrounding whitespace without changing case."""
    if not isinstance(license_key, str):
        return ""

    return license_key.strip()


def is_recognized_license(license_key):
    """Check key recognition only, not user entitlement."""
    key = normalize_license_key(license_key)

    return bool(key) and key in get_allowed_licenses()


def validate_license(license_key):
    """
    Return a recognition result.

    Never use this result alone to start a bot or send orders.
    """
    key = normalize_license_key(license_key)

    if not key:
        return {
            "recognized": False,
            "authorized": False,
            "reason": "LICENSE_KEY_REQUIRED",
        }

    if key not in get_allowed_licenses():
        return {
            "recognized": False,
            "authorized": False,
            "reason": "LICENSE_KEY_NOT_ALLOWED",
        }

    return {
        "recognized": True,
        "authorized": False,
        "reason": "SERVER_SIDE_ENTITLEMENT_CHECK_REQUIRED",
    }
