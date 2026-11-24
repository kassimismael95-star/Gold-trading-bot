import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Licence, User


class LicenseManager:
    def __init__(self, session: Session):
        self.session = session

    def get_allowed_licence_codes(self) -> list[str]:
        raw_codes = os.getenv("ALLOWED_LICENSES", "")

        return [code.strip() for code in raw_codes.split(",") if code.strip()]

    def is_code_allowed(self, code: str) -> bool:
        return code.strip().upper() in self.get_allowed_licence_codes()

    def get_licence_by_code(self, code: str) -> Licence | None:
        statement = select(Licence).where(
            Licence.code == code.strip().upper()
        )

        return self.session.scalar(statement)

    def activate_licence(
        self,
        code: str,
        user: User,
        plan: str = "standard",
        valid_days: int | None = None,
    ) -> Licence:
        code = code.strip().upper()

        if not self.is_code_allowed(code):
            raise ValueError("This licence code is not recognized.")

        licence = self.get_licence_by_code(code)

        if not licence:
            licence = Licence(
                code=code,
                plan=plan,
                status="active",
                user_id=user.id,
                activated_at=datetime.now(timezone.utc),
            )

            if valid_days:
                licence.expires_at = datetime.now(timezone.utc) + timedelta(days=valid_days)

            self.session.add(licence)
            self.session.commit()
            self.session.refresh(licence)

            return licence

        if licence.status == "revoked":
            raise ValueError("This licence code has been revoked.")

        if licence.user_id and licence.user_id != user.id:
            raise ValueError("This licence code is already assigned to another user.")

        licence.user_id = user.id
        licence.status = "active"
        licence.plan = plan
        licence.activated_at = datetime.now(timezone.utc)

        if valid_days:
            licence.expires_at = datetime.now(timezone.utc) + timedelta(days=valid_days)

        self.session.commit()
        self.session.refresh(licence)

        return licence

    def validate_user_licence(self, user: User) -> Licence:
        statement = select(Licence).where(
            Licence.user_id == user.id,
            Licence.status == "active",
        )

        licence = self.session.scalar(statement)

        if not licence:
            raise ValueError("No active licence found for this user.")

        if licence.expires_at and licence.expires_at < datetime.now(timezone.utc):
            licence.status = "expired"
            self.session.commit()
            raise ValueError("This licence has expired.")

        return licence

    def suspend_licence(self, code: str) -> Licence:
        licence = self.get_licence_by_code(code)

        if not licence:
            raise ValueError("Licence not found.")

        licence.status = "suspended"
        self.session.commit()
        self.session.refresh(licence)

        return licence

    def revoke_licence(self, code: str) -> Licence:
        licence = self.get_licence_by_code(code)

        if not licence:
            raise ValueError("Licence not found.")

        licence.status = "revoked"
        licence.user_id = None
        licence.activated_at = None
        licence.expires_at = None

        self.session.commit()
        self.session.refresh(licence)

        return licence

    def reactivate_licence(self, code: str, user: User) -> Licence:
        licence = self.get_licence_by_code(code)

        if not licence:
            raise ValueError("Licence not found.")

        if not self.is_code_allowed(licence.code):
            raise ValueError("This licence code is not recognized.")

        licence.status = "active"
        licence.user_id = user.id
        licence.activated_at = datetime.now(timezone.utc)

        self.session.commit()
        self.session.refresh(licence)

        return licence
