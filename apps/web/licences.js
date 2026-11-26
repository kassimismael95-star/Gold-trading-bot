
from datetime import datetime, timezone

from ..models import Entitlement


# Licence codes configured in config/licences.json
VIP_CODES = {
    "BOSSMODE98",
    "BOSSMODE99",
}

TRIAL_CODE = "BOSSMODE01D"
PAID_CODE = "BOSSMODE30D"

TRIAL_HOURS = 24
TRIAL_COOLDOWN_HOURS = 96
MAX_TRIALS = 2


def _aware(value):
    """Treat legacy naive database timestamps as UTC."""
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def active_entitlement(user_id, now=None):
    """
    Return the user's most recent currently-active entitlement.

    Lifetime VIP entitlements have no expiry.
    Time-limited trial and paid entitlements must not be expired.
    """
    now = _aware(now or datetime.now(timezone.utc))

    rows = (
        Entitlement.query
        .filter_by(user_id=user_id, status="ACTIVE")
        .order_by(Entitlement.id.desc())
        .all()
    )

    for row in rows:
        expiry = _aware(row.expires_at)

        # None expiry means lifetime access, used by assigned VIP codes.
        if expiry is None or expiry > now:
            return row

    return None


def can_start_new_entries(user_id, now=None):
    """
    Check the entitlement gate for opening new trades.

    This is an entitlement check only. Trading risk limits,
    account permissions, and broker execution checks must also pass.
    """
    return active_entitlement(user_id, now) is not None
