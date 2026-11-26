
from flask import Flask, jsonify, send_from_directory
from datetime import timedelta
from flask_cors import CORS

from .config import Settings
from .extensions import db, migrate, jwt


def create_app(settings=None):
    s = settings or Settings()

    if s.app_env == "production":
        from .config import validate_production_settings
        validate_production_settings(s)

    database_url = s.database_url

    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]

    app = Flask(__name__, static_folder="../web", static_url_path="/")

    app.config.update(
        APP_ENV=s.app_env,
        SECRET_KEY=s.secret_key,
        SQLALCHEMY_DATABASE_URI=database_url,
        ALLOW_LIVE_TRADING=s.allow_live_trading,
        MAX_CONTENT_LENGTH=1048576,
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=30),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=14),
        JWT_TOKEN_LOCATION=["headers"],
        FLW_PUBLIC_KEY=s.flw_public_key,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY=s.jwt_secret_key,
        AGENT_SHARED_SECRET=s.agent_shared_secret,
        FLW_SECRET_KEY=s.flw_secret_key,
        FLW_WEBHOOK_HASH=s.flw_webhook_hash,
        FLW_REDIRECT_URL=s.flw_redirect_url
    )

    origins = [
        x.strip()
        for x in s.cors_origins.split(",")
        if x.strip()
    ]

    CORS(app, resources={r"/api/*": {"origins": origins}})

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    @jwt.token_in_blocklist_loader
    def is_token_revoked(jwt_header, jwt_payload):
        try:
            from .models import TokenBlocklist, User

            user = User.query.get(int(jwt_payload.get("sub")))

            if not user:
                return True

            if int(jwt_payload.get("session_version", 0)) != int(user.session_version or 0):
                return True

            row = TokenBlocklist.query.filter_by(
                jti=jwt_payload.get("jti")
            ).first()

            if not row:
                return False

            expiry = row.expires_at

            if expiry.tzinfo is None:
                expiry = expiry.replace(
                    tzinfo=__import__("datetime").timezone.utc
                )

            return expiry > __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            )

        except Exception:
            app.logger.exception("JWT blocklist check failed")
            return True

    from . import models

    from .auth.routes import bp as auth_bp
    from .accounts.routes import bp as accounts_bp

    # Corrected import: matches apps/api/trading/commands/routes.py
    from .trading.commands.routes import bp as agent_bp

    from .licences.routes import bp as licences_bp
    from .subscriptions.routes import bp as subscriptions_bp
    from .payments.routes import bp as payments_bp
    from .dashboard.routes import bp as dashboard_bp
    from .admin.routes import bp as admin_bp
    from .ea.routes import bp as ea_bp
    from .agent_routes import bp as agent_control_bp
    from .payments.wallet_routes import bp as wallet_bp

    blueprints = (
        auth_bp,
        accounts_bp,
        agent_bp,
        agent_control_bp,
        licences_bp,
        subscriptions_bp,
        payments_bp,
        dashboard_bp,
        admin_bp,
        ea_bp,
        wallet_bp
    )

    for bp in blueprints:
        app.register_blueprint(bp)

    @app.get("/api/health/live")
    def live():
        return jsonify(status="alive")

    @app.get("/api/health/ready")
    def ready():
        try:
            from sqlalchemy import text
            db.session.execute(text("SELECT 1"))
            connected = True
        except Exception:
            connected = False

        return jsonify(
            status="ready" if connected else "not_ready",
            database_connected=connected,
            mt5_execution="external_agent_required",
            live_trading_enabled=bool(
                app.config.get("ALLOW_LIVE_TRADING", False)
            )
        ), 200 if connected else 503

    @app.get("/")
    def home():
        return send_from_directory(app.static_folder, "index.html")

    @app.errorhandler(404)
    def not_found(e):
        return jsonify(error="not_found"), 404

    with app.app_context():
        import os

        auto_create = str(
            os.getenv("AUTO_CREATE_DB", "")
        ).lower() in {"1", "true", "yes"}

        if s.app_env != "production" or auto_create:
            db.create_all()

        email = s.bootstrap_admin_email
        password = s.bootstrap_admin_password

        if email and password:
            from .models import User

            if not User.query.filter_by(email=email.lower()).first():
                user = User(email=email.lower(), role="admin")
                user.set_password(password)
                db.session.add(user)
                db.session.commit()

    if (
        s.app_env == "production"
        and str(os.getenv("ENABLE_BALANCE_SYNC_LOOP", "false")).lower()
        in {"1", "true", "yes"}
    ):
        from .payments.payment_scheduler import start_periodic_balance_sync

        start_periodic_balance_sync(
            app,
            int(os.getenv("BALANCE_SYNC_INTERVAL_SECONDS", "3600"))
        )

    return app


app = create_app()


if __name__ == "__main__":
    import os

    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000"))
    )
