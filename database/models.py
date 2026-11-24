import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow():
    return datetime.now(timezone.utc)


def new_uuid():
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="customer", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    licences: Mapped[list["Licence"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    accounts: Mapped[list["TradingAccount"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    bots: Mapped[list["Bot"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Licence(Base):
    __tablename__ = "licences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    plan: Mapped[str] = mapped_column(String(30), default="standard", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    user: Mapped[User | None] = relationship(back_populates="licences")


class TradingAccount(Base):
    __tablename__ = "trading_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    broker_name: Mapped[str] = mapped_column(String(100), nullable=False)
    mt5_login: Mapped[str] = mapped_column(String(50), nullable=False)
    mt5_server: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_password: Mapped[str] = mapped_column(Text, nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), default="demo", nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), default="XAUUSD", nullable=False)
    connection_status: Mapped[str] = mapped_column(String(20), default="disconnected", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "mt5_login", "mt5_server", name="uq_user_mt5_account"),
    )

    user: Mapped[User] = relationship(back_populates="accounts")
    bots: Mapped[list["Bot"]] = relationship(back_populates="account", cascade="all, delete-orphan")


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trading_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), default="Gold Scalper", nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), default="XAUUSD", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="stopped", nullable=False)
    trading_mode: Mapped[str] = mapped_column(String(10), default="demo", nullable=False)
    risk_per_trade_percent: Mapped[float] = mapped_column(Numeric(6, 3), default=0.5, nullable=False)
    max_open_positions: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    daily_loss_limit_percent: Mapped[float] = mapped_column(Numeric(6, 3), default=3.0, nullable=False)
    max_daily_trades: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_spread_points: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    stop_loss_points: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    take_profit_points: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    emergency_stop: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="bots")
    account: Mapped[TradingAccount] = relationship(back_populates="bots")
    commands: Mapped[list["Command"]] = relationship(back_populates="bot", cascade="all, delete-orphan")
    trades: Mapped[list["Trade"]] = relationship(back_populates="bot", cascade="all, delete-orphan")


class ExecutionNode(Base):
    __tablename__ = "execution_nodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    region: Mapped[str] = mapped_column(String(100), default="unknown", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="offline", nullable=False)
    max_accounts: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    active_accounts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    workers: Mapped[list["Worker"]] = relationship(back_populates="execution_node", cascade="all, delete-orphan")


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    execution_node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    worker_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="offline", nullable=False)
    assigned_account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trading_accounts.id", ondelete="SET NULL"))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    execution_node: Mapped[ExecutionNode] = relationship(back_populates="workers")


class Command(Base):
    __tablename__ = "commands"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    bot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    command_type: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    assigned_worker_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workers.id", ondelete="SET NULL"))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    bot: Mapped[Bot] = relationship(back_populates="commands")


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    bot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True)
    command_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("commands.id", ondelete="SET NULL"))
    broker_ticket: Mapped[str | None] = mapped_column(String(100), index=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    volume: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    entry_price: Mapped[float | None] = mapped_column(Numeric(18, 8))
    exit_price: Mapped[float | None] = mapped_column(Numeric(18, 8))
    profit: Mapped[float | None] = mapped_column(Numeric(18, 8))
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    comment: Mapped[str | None] = mapped_column(String(100))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    bot: Mapped[Bot] = relationship(back_populates="trades")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
