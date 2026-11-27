from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from .extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="customer")
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    session_version = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)


class TradingAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    label = db.Column(db.String(80), nullable=False)
    broker = db.Column(db.String(80), nullable=False, default="Exness")
    login = db.Column(db.String(40), nullable=False)
    server = db.Column(db.String(120), nullable=False)
    mode = db.Column(db.String(10), nullable=False, default="demo")
    symbol = db.Column(db.String(40), nullable=False, default="AUTO")
    risk_settings = db.Column(db.JSON, nullable=False, default=dict)
    desired_state = db.Column(db.String(12), nullable=False, default="STOPPED")
    actual_state = db.Column(db.String(20), nullable=False, default="UNKNOWN")
    agent_id = db.Column(db.String(80), nullable=True, index=True)
    is_deleted = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=db.false(),
    )
    ea_token_hash = db.Column(db.String(64), nullable=True)
    ea_token_version = db.Column(db.Integer, nullable=False, default=1)
    ea_token_ciphertext = db.Column(db.Text, nullable=True)
    last_seen = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class Agent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.String(80), unique=True, nullable=False)
    hostname = db.Column(db.String(120), nullable=True)
    last_seen = db.Column(db.DateTime(timezone=True), nullable=True)
    status = db.Column(db.String(20), default="OFFLINE")
    secret_hash = db.Column(db.String(64), nullable=True)
    capacity = db.Column(db.Integer, nullable=False, default=20)
    metrics = db.Column(db.JSON, nullable=False, default=dict)


class Command(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("trading_account.id"), nullable=False, index=True)
    command = db.Column(db.String(20), nullable=False)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    status = db.Column(db.String(20), nullable=False, default="PENDING", index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    claimed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    result = db.Column(db.JSON, nullable=True)


class AccountEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("trading_account.id"), nullable=False, index=True)
    event_type = db.Column(db.String(40), nullable=False)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    event_key = db.Column(db.String(120), nullable=True, unique=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class Entitlement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    code = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="ACTIVE")
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    tx_ref = db.Column(db.String(100), unique=True, nullable=False)
    plan_code = db.Column(db.String(30), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="PENDING")
    provider_id = db.Column(db.String(100), nullable=True, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


# Wallet and reconciliation records.
# These records do not replace the payment provider's actual balance.
class Wallet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    currency = db.Column(db.String(3), nullable=False, default="USD")
    ledger_balance = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


db.Index(
    "uq_merchant_wallet_currency",
    Wallet.currency,
    unique=True,
    postgresql_where=Wallet.owner_user_id.is_(None),
    sqlite_where=Wallet.owner_user_id.is_(None),
)


class WalletTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey("wallet.id"), nullable=False, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payment.id"), nullable=True, unique=True)
    provider_transaction_id = db.Column(db.String(100), nullable=True, unique=True)
    reference = db.Column(db.String(120), nullable=False, unique=True)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    kind = db.Column(db.String(24), nullable=False, default="PAYMENT")
    status = db.Column(db.String(20), nullable=False, default="POSTED")
    provider_confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class WalletBalanceSnapshot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(
        db.Integer,
        db.ForeignKey("wallet.id"),
        nullable=False,
        index=True,
    )
    currency = db.Column(db.String(3), nullable=False)
    provider_balance = db.Column(db.Numeric(14, 2), nullable=False)
    available_balance = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    ledger_balance = db.Column(db.Numeric(14, 2), nullable=False)
    checked_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    provider = db.Column(db.String(40), nullable=False, default="flutterwave")
    status = db.Column(db.String(20), nullable=False, default="OBSERVED")


class WalletReconciliation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(
        db.Integer,
        db.ForeignKey("wallet_balance_snapshot.id"),
        nullable=True,
        index=True,
    )
    currency = db.Column(db.String(3), nullable=False)
    provider_balance = db.Column(db.Numeric(14, 2), nullable=False)
    ledger_balance = db.Column(db.Numeric(14, 2), nullable=False)
    difference = db.Column(db.Numeric(14, 2), nullable=False)
    status = db.Column(db.String(24), nullable=False, default="UNMATCHED")
    note = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class PaymentWebhookEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_key = db.Column(db.String(160), nullable=False, unique=True)
    event_type = db.Column(db.String(80), nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    processed = db.Column(db.Boolean, nullable=False, default=False)
    received_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class PaymentRefund(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payment.id"), nullable=False, index=True)
    provider_refund_id = db.Column(db.String(100), nullable=True, unique=True)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    status = db.Column(db.String(24), nullable=False, default="REQUESTED")
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class PaymentDispute(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payment.id"), nullable=False, index=True)
    provider_case_id = db.Column(db.String(100), nullable=True, unique=True)
    status = db.Column(db.String(24), nullable=False, default="OPEN")
    details = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class AccountCredential(db.Model):
    """Encrypted broker secret, scoped to one trading account."""
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(
        db.Integer,
        db.ForeignKey("trading_account.id"),
        unique=True,
        nullable=False,
        index=True,
    )
    password_ciphertext = db.Column(db.Text, nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    revoked = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class EmailChallenge(db.Model):
    """Hashed one-time email verification and password-reset challenge."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    purpose = db.Column(db.String(24), nullable=False, index=True)
    salt = db.Column(db.String(64), nullable=False)
    code_hash = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    consumed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    action = db.Column(db.String(80), nullable=False, index=True)
    target_type = db.Column(db.String(40), nullable=True)
    target_id = db.Column(db.String(80), nullable=True)
    details = db.Column(db.JSON, nullable=False, default=dict)
    remote_addr = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class RateLimitRecord(db.Model):
    key_hash = db.Column(db.String(64), primary_key=True)
    count = db.Column(db.Integer, nullable=False, default=0)
    window_start = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payment.id"), nullable=False, unique=True, index=True)
    plan_code = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="ACTIVE", index=True)
    starts_at = db.Column(db.DateTime(timezone=True), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class TokenBlocklist(db.Model):
    jti = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    revoked_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class AccountTelemetry(db.Model):
    account_id = db.Column(
        db.Integer,
        db.ForeignKey("trading_account.id"),
        primary_key=True,
    )
    balance = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    equity = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    free_margin = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    floating_pnl = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    open_positions_count = db.Column(db.Integer, nullable=False, default=0)
    active_symbol = db.Column(db.String(40), nullable=True)
    entries_enabled = db.Column(db.Boolean, nullable=False, default=False)
    connected_to_broker = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
