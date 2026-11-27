
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    secret_key: str = os.getenv("APP_SECRET_KEY", "dev-only-change-me")
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "dev-jwt-change-me")
    database_url: str = os.getenv(
        "DATABASE_URL", "sqlite:///gold_scalper_dev.db"
    )
    cors_origins: str = os.getenv(
        "CORS_ORIGINS", "http://localhost:5000"
    )
    agent_shared_secret: str = os.getenv("AGENT_SHARED_SECRET", "")

    bootstrap_admin_email: str = os.getenv(
        "BOOTSTRAP_ADMIN_EMAIL", ""
    )
    bootstrap_admin_password: str = os.getenv(
        "BOOTSTRAP_ADMIN_PASSWORD", ""
    )

    flw_public_key: str = os.getenv("FLW_PUBLIC_KEY", "")
    flw_secret_key: str = os.getenv("FLW_SECRET_KEY", "")
    flw_webhook_hash: str = os.getenv("FLW_WEBHOOK_HASH", "")
    flw_redirect_url: str = os.getenv("FLW_REDIRECT_URL", "")

    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))

    allow_live_trading: bool = (
        os.getenv("ALLOW_LIVE_TRADING", "false").lower()
        in {"1", "true", "yes"}
    )


def validate_production_settings(settings):
    """Fail closed when production secrets or required providers are absent."""
    import base64

    required = {
        "APP_SECRET_KEY": settings.secret_key,
        "JWT_SECRET_KEY": settings.jwt_secret_key,
        "AGENT_SHARED_SECRET": settings.agent_shared_secret,
        "FLW_SECRET_KEY": settings.flw_secret_key,
        "FLW_WEBHOOK_HASH": settings.flw_webhook_hash,
        "FLW_REDIRECT_URL": settings.flw_redirect_url,
        "CREDENTIAL_ENCRYPTION_KEY": os.getenv(
            "CREDENTIAL_ENCRYPTION_KEY", ""
        ),
        "SMTP_HOST": os.getenv("SMTP_HOST", ""),
        "EMAIL_FROM": os.getenv("EMAIL_FROM", ""),
        "CORS_ORIGINS": settings.cors_origins,
        "BOOTSTRAP_ADMIN_EMAIL": settings.bootstrap_admin_email,
        "BOOTSTRAP_ADMIN_PASSWORD": settings.bootstrap_admin_password,
    }

    missing = [
        name
        for name, value in required.items()
        if not str(value or "").strip()
    ]

    if missing:
        raise RuntimeError(
            "production_configuration_missing:" + ",".join(missing)
        )

    for name in (
        "APP_SECRET_KEY",
        "JWT_SECRET_KEY",
        "AGENT_SHARED_SECRET",
    ):
        value = str(required[name])

        if (
            len(value) < 32
            or value in {"dev-only-change-me", "dev-jwt-change-me"}
        ):
            raise RuntimeError(
                name
                + "_must_be_a_unique_random_secret_of_at_least_32_characters"
            )

    origins = [
        x.strip()
        for x in str(settings.cors_origins).split(",")
        if x.strip()
    ]

    if not origins or "*" in origins:
        raise RuntimeError(
            "CORS_ORIGINS_must_be_explicit_in_production"
        )

    if any(not x.startswith("https://") for x in origins):
        raise RuntimeError(
            "production_CORS_origins_must_use_HTTPS"
        )

    if not str(settings.flw_redirect_url).startswith("https://"):
        raise RuntimeError("FLW_REDIRECT_URL_must_use_HTTPS")

    if not 1 <= settings.smtp_port <= 65535:
        raise RuntimeError("SMTP_PORT_out_of_range")

    if len(str(settings.bootstrap_admin_password)) < 12:
        raise RuntimeError(
            "BOOTSTRAP_ADMIN_PASSWORD_must_be_at_least_12_characters"
        )

    if "@" not in str(settings.bootstrap_admin_email):
        raise RuntimeError("BOOTSTRAP_ADMIN_EMAIL_must_be_valid")

    if not settings.database_url.startswith(
        ("postgresql://", "postgres://", "postgresql+psycopg://")
    ):
        raise RuntimeError(
            "production_requires_persistent_postgresql"
        )

    raw = str(required["CREDENTIAL_ENCRYPTION_KEY"])

    try:
        key = base64.urlsafe_b64decode(
            raw + "=" * ((4 - len(raw) % 4) % 4)
        )
    except Exception as exc:
        raise RuntimeError(
            "invalid_CREDENTIAL_ENCRYPTION_KEY"
        ) from exc

    if len(key) != 32:
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY_must_decode_to_32_bytes"
        )

    return True
