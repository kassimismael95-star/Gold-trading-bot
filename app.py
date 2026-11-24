"""
Render control-plane entry point.

This app manages users, MT5 account credentials, bot sessions,
commands, workers, and API routes. It does not execute trades
directly; execution workers do that in isolated MT5 sessions.
"""

import os

from flask import Flask, jsonify
from flask_cors import CORS

from database.models import initialize_database
from database.migrations import run_migrations
from web.routes import api


def create_app():
    app = Flask(__name__)

    CORS(
        app,
        supports_credentials=True,
        origins=os.environ.get(
            "ALLOWED_ORIGINS",
            "*"
        ).split(",")
    )

    app.register_blueprint(api)

    @app.route("/")
    def home():
        return jsonify({
            "service": "BOSSMODE Control Plane",
            "status": "running"
        })

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({
            "status": "ok"
        })

    return app


app = create_app()


def initialize():
    initialize_database()
    run_migrations()


if __name__ == "__main__":
    initialize()

    port = int(
        os.environ.get("PORT", 5000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
