
import os
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from sqlalchemy import text

from .config import Settings
from .extensions import db, migrate, jwt


def create_app(settings=None):
    s = settings or Settings()

    if s.app_env == "production":
        from .config import validate_production_settings
        validate_production_settings(s)

    database_url = s.database_url

    if database_url.startswith("postgres://"):
        database_url = (
            "postgresql+psycopg://"
            + database_url[len("postgres://"):]
        )
    elif database_url.startswith("postgresql://"):
        database_url = (
            "postgresql+psycopg://"
            + database_url[len("postgresql://"):]
        )

    app = Flask(
        __name__,
        static_folder="../web",
        static_url_path="/"
    )

    app.config.update(
        APP_ENV=s.app_env,
        SECRET_KEY=s.secret_key,
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,

        ALLOW_LIVE_TRADING=s.allow_live_trading,

        MAX_CONTENT_LENGTH=1048576,

        JWT_SECRET_KEY=s.jwt_secret_key,
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=30),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=14),
        JWT_TOKEN_LOCATION=["headers"],

        AGENT_SHARED_SECRET=s.agent_shared_secret,

        FLW_PUBLIC_KEY=s.flw_public_key,
        FLW_SECRET_KEY=s.flw_secret_key,
        FLW_WEBHOOK_HASH=s.flw_webhook_hash,
        FLW_REDIRECT_URL=s.flw_redirect_url
    )

    origins = [
        origin.strip()
        for origin in s.cors_origins.split(",")
        if origin.strip()
    ]

    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": origins
            }
        }
    )

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    # JWT token revocation and session-version validation
    @jwt.token_in_blocklist_loader
    def is_token_revoked(jwt_header, jwt_payload):
        try:
            from .models import TokenBlocklist, User

            identity = jwt_payload.get("sub")

            if identity is None:
                return True

            try:
                user_id = int(identity)
            except (TypeError, ValueError):
                return True

            user = db.session.get(User, user_id)

            if user is None:
                return True

            token_version = int(
                jwt_payload.get("session_version", 0)
            )

            current_version = int(
                user.session_version or 0
            )

            if token_version != current_version:
                return True

            jti = jwt_payload.get("jti")

            if not jti:
                return True

            row = TokenBlocklist.query.filter_by(
                jti=jti
            ).first()

            if row is None:
                return False

            expiry = row.expires_at

            if expiry.tzinfo is None:
                expiry = expiry.replace(
                    tzinfo=timezone.utc
                )

            return expiry > datetime.now(timezone.utc)

        except Exception:
            app.logger.exception(
                "JWT blocklist check failed"
            )
            return True

    # Import models before registering application blueprints
    from . import models

    # Application blueprints
    from .auth.routes import bp as auth_bp
    from .accounts.routes import bp as accounts_bp

    # Oracle agent command queue
    from .trading.commands.routes import bp as agent_bp

    # Oracle agent registration and management
    from .agent.routes import bp as agent_control_bp

    from .licences.routes import bp as licences_bp
    from .subscriptions.routes import bp as subscriptions_bp
    from .payments.routes import bp as payments_bp
    from .payments.wallet_routes import bp as wallet_bp
    from .dashboard.routes import bp as dashboard_bp
    from .admin.routes import bp as admin_bp
    from .ea.routes import bp as ea_bp

    blueprints = (
        auth_bp,
        accounts_bp,
        agent_bp,
        agent_control_bp,
        licences_bp,
        subscriptions_bp,
        payments_bp,
        wallet_bp,
        dashboard_bp,
        admin_bp,
        ea_bp
    )

    for blueprint in blueprints:
        app.register_blueprint(blueprint)

    # Liveness health check
    @app.get("/api/health/live")
    def live():
        return jsonify(
            status="alive"
        ), 200

    # Database readiness health check
    @app.get("/api/health/ready")
    def ready():
        try:
            db.session.execute(text("SELECT 1"))

            return jsonify(
                status="ready",
                database_connected=True,
                mt5_execution="external_agent_required",
                live_trading_enabled=bool(
                    app.config.get(
                        "ALLOW_LIVE_TRADING",
                        False
                    )
                )
            ), 200

        except Exception:
            app.logger.exception(
                "Database readiness check failed"
            )

            db.session.rollback()

            return jsonify(
                status="not_ready",
                database_connected=False,
                mt5_execution="external_agent_required",
                live_trading_enabled=bool(
                    app.config.get(
                        "ALLOW_LIVE_TRADING",
                        False
                    )
                )
            ), 503

    # Main web application
    @app.get("/")
    def home():
        return send_from_directory(
            app.static_folder,
            "index.html"
        )

    # API 404 response
    @app.errorhandler(404)
    def not_found(error):
        return jsonify(
            error="not_found"
        ), 404

    # Database initialization and administrator bootstrap
    with app.app_context():
        auto_create = str(
            os.getenv("AUTO_CREATE_DB", "")
        ).lower() in {"1", "true", "yes"}

        if s.app_env != "production" or auto_create:
            db.create_all()

        # Safe PostgreSQL repair for the missing account column
        if db.engine.dialect.name == "postgresql":
            with db.engine.begin() as conn:
                table_exists = conn.execute(
                    text(
                        "SELECT to_regclass('public.trading_account')"
                    )
                ).scalar()

                if table_exists:
                    conn.execute(
                        text("""
                            ALTER TABLE public.trading_account
                            ADD COLUMN IF NOT EXISTS
                            is_deleted BOOLEAN NOT NULL DEFAULT FALSE
                        """)
                    )

                    app.logger.info(
                        "Database check: "
                        "trading_account.is_deleted is ready"
                    )
                else:
                    app.logger.warning(
                        "Database repair skipped: "
                        "public.trading_account does not exist"
                    )

        email = s.bootstrap_admin_email
        password = s.bootstrap_admin_password

        if email and password:
            from .models import User

            normalized_email = email.strip().lower()

            existing_admin = User.query.filter_by(
                email=normalized_email
            ).first()

            if existing_admin is None:
                user = User(
                    email=normalized_email,
                    role="admin"
                )

                user.set_password(password)

                db.session.add(user)
                db.session.commit()

    # Optional periodic wallet balance synchronization
    if (
        s.app_env == "production"
        and str(
            os.getenv(
                "ENABLE_BALANCE_SYNC_LOOP",
                "false"
            )
        ).lower() in {"1", "true", "yes"}
    ):
        from .payments.payment_scheduler import (
            start_periodic_balance_sync
        )

        start_periodic_balance_sync(
            app,
            int(
                os.getenv(
                    "BALANCE_SYNC_INTERVAL_SECONDS",
                    "3600"
                )
            )
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv("PORT", "5000")
        )
    )
