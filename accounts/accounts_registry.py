from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from accounts.credential_vault import CredentialVault
from database.models import TradingAccount, User


class AccountRegistry:
    def __init__(self, session: Session, credential_vault: CredentialVault):
        self.session = session
        self.vault = credential_vault

    def create_account(
        self,
        user: User,
        broker_name: str,
        mt5_login: str,
        mt5_password: str,
        mt5_server: str,
        symbol: str = "XAUUSD",
        account_type: str = "demo",
    ) -> TradingAccount:
        if not user:
            raise ValueError("User is required.")

        if not broker_name or not broker_name.strip():
            raise ValueError("Broker name is required.")

        if not mt5_login or not mt5_login.strip():
            raise ValueError("MT5 login is required.")

        if not mt5_password:
            raise ValueError("MT5 password is required.")

        if not mt5_server or not mt5_server.strip():
            raise ValueError("MT5 server is required.")

        if account_type not in {"demo", "live"}:
            raise ValueError("Account type must be demo or live.")

        existing = self.get_account_by_login(
            user_id=user.id,
            mt5_login=mt5_login,
            mt5_server=mt5_server,
        )

        if existing:
            raise ValueError("This MT5 account is already connected to your profile.")

        account = TradingAccount(
            user_id=user.id,
            broker_name=broker_name.strip(),
            mt5_login=mt5_login.strip(),
            mt5_server=mt5_server.strip(),
            encrypted_password=self.vault.encrypt(mt5_password),
            symbol=symbol.strip().upper(),
            account_type=account_type,
            connection_status="disconnected",
            is_active=True,
        )

        self.session.add(account)
        self.session.commit()
        self.session.refresh(account)

        return account

    def get_account(self, user_id, account_id) -> TradingAccount | None:
        statement = select(TradingAccount).where(
            TradingAccount.id == account_id,
            TradingAccount.user_id == user_id,
        )

        return self.session.scalar(statement)

    def get_account_by_login(self, user_id, mt5_login: str, mt5_server: str) -> TradingAccount | None:
        statement = select(TradingAccount).where(
            TradingAccount.user_id == user_id,
            TradingAccount.mt5_login == mt5_login.strip(),
            TradingAccount.mt5_server == mt5_server.strip(),
        )

        return self.session.scalar(statement)

    def list_accounts(self, user_id) -> list[TradingAccount]:
        statement = (
            select(TradingAccount)
            .where(TradingAccount.user_id == user_id)
            .order_by(TradingAccount.created_at.desc())
        )

        return list(self.session.scalars(statement))

    def update_connection_status(self, account: TradingAccount, status: str) -> TradingAccount:
        allowed_statuses = {"connected", "disconnected", "error", "testing"}

        if status not in allowed_statuses:
            raise ValueError("Invalid connection status.")

        account.connection_status = status
        account.updated_at = datetime.now(timezone.utc)

        self.session.commit()
        self.session.refresh(account)

        return account

    def deactivate_account(self, account: TradingAccount) -> TradingAccount:
        account.is_active = False
        account.connection_status = "disconnected"
        account.updated_at = datetime.now(timezone.utc)

        self.session.commit()
        self.session.refresh(account)

        return account

    def get_decrypted_password(self, account: TradingAccount) -> str:
        return self.vault.decrypt(account.encrypted_password)
