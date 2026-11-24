import os

from flask import Flask, jsonify
from flask_cors import CORS

from database.migrations import run_migrations
from web.routes import register_routes


def create_app() -> Flask:
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "")
    app.config["JSON_SORT_KEYS"] = False

    allowed_origins = os.getenv("ALLOWED_ORIGINS", "")

    if allowed_origins:
        origins = [origin.strip() for origin in allowed_origins.split(",") if origin.strip()]
        CORS(
            app,
            origins=origins,
            supports_credentials=True,
            allow_headers=["Content-Type", "Authorization"],
            methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        )
    else:
        CORS(app)

    register_routes(app)

    @app.get("/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "service": "Gold Scalper AI - Matrix Control",
                "live_trading_enabled": os.getenv("ENABLE_LIVE_TRADING", "false").lower() == "true",
            }
        )

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def internal_error(_error):
        return jsonify({"error": "Internal server error"}), 500

    return app


app = create_app()


if __name__ == "__main__":
    run_migrations()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
