import os
from typing import Any

from flask import Flask, jsonify, request
from flask_cors import CORS

from worker.command_executor import CommandExecutor
from worker.mt5_client import MT5Client

app = Flask(__name__)

CORS(
    app,
    resources={r"/*": {"origins": "*"}},
)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = (
        "GET, POST, PUT, DELETE, OPTIONS, HEAD"
    )
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization, X-Worker-Secret, X-Requested-With, Accept"
    )
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate"
    )

    return response


mt5_client = MT5Client()
command_executor = CommandExecutor(mt5_client=mt5_client)


def get_worker_id() -> str:
    return os.environ.get(
        "WORKER_ID",
        "local-worker",
    ).strip()


def get_shared_secret() -> str:
    return os.environ.get(
        "WORKER_SHARED_SECRET",
        "",
    ).strip()


def is_authorized() -> bool:
    provided_secret = request.headers.get(
        "X-Worker-Secret",
        "",
    ).strip()

    expected_secret = get_shared_secret()

    if not expected_secret:
        return False

    return provided_secret == expected_secret


def extract_request_data() -> dict[str, Any]:
    data = {}

    try:
        data = request.get_json(
            force=True,
            silent=True,
        ) or {}

    except Exception:
        data = {}

    if not data and request.form:
        data = request.form.to_dict()

    if not data and request.data:
        try:
            import json

            data = json.loads(
                request.data.decode("utf-8")
            )

        except Exception:
            data = {}

    return data or {}


@app.route("/", methods=["GET"])
def health_root():
    return jsonify(
        {
            "status": "online",
            "service": "Gold Scalper Isolated MT5 Worker",
            "worker_id": get_worker_id(),
        }
    )


@app.route("/health", methods=["GET"])
@app.route("/ping", methods=["GET"])
def health_ping():
    return jsonify(
        {
            "status": "healthy",
            "worker_id": get_worker_id(),
            "mt5_connected": mt5_client.connected,
            "active_symbol": mt5_client.active_symbol,
        }
    )


@app.route("/workers/<worker_id>/status", methods=["GET"])
def worker_status(worker_id: str):
    if not is_authorized():
        return jsonify(
            {
                "status": "error",
                "message": "Unauthorized worker request.",
            }
        ), 401

    if worker_id != get_worker_id():
        return jsonify(
            {
                "status": "error",
                "message": "Worker ID does not match this worker.",
            }
        ), 403

    return jsonify(
        {
            "status": "online",
            "worker_id": worker_id,
            "mt5_connected": mt5_client.connected,
            "active_symbol": mt5_client.active_symbol,
        }
    )


@app.route("/workers/<worker_id>/connect", methods=["POST"])
def connect_mt5(worker_id: str):
    if not is_authorized():
        return jsonify(
            {
                "status": "error",
                "message": "Unauthorized worker request.",
            }
        ), 401

    if worker_id != get_worker_id():
        return jsonify(
            {
                "status": "error",
                "message": "Worker ID does not match this worker.",
            }
        ), 403

    data = extract_request_data()

    login = str(
        data.get("mt5_login", "")
    ).strip()

    password = str(
        data.get("mt5_password", "")
    ).strip()

    server = str(
        data.get("mt5_server", "")
    ).strip()

    symbol = str(
        data.get("mt5_symbol", "XAUUSDm")
    ).strip()

    if not login or not password or not server:
        return jsonify(
            {
                "status": "error",
                "message": "MT5 login, password, and server are required.",
            }
        ), 400

    init_result = mt5_client.initialize()

    if not init_result.connected:
        return jsonify(
            {
                "status": "error",
                "message": init_result.message,
            }
        ), 500

    login_result = mt5_client.login(
        login=login,
        password=password,
        server=server,
    )

    if not login_result.connected:
        return jsonify(
            {
                "status": "error",
                "message": login_result.message,
            }
        ), 401

    active_symbol = mt5_client.resolve_gold_symbol(symbol)

    return jsonify(
        {
            "status": "success",
            "worker_id": worker_id,
            "mt5_connected": True,
            "active_symbol": active_symbol,
            "account": login_result.account_info,
        }
    )


@app.route("/workers/<worker_id>/commands", methods=["POST"])
def execute_command(worker_id: str):
    if not is_authorized():
        return jsonify(
            {
                "status": "error",
                "message": "Unauthorized worker request.",
            }
        ), 401

    if worker_id != get_worker_id():
        return jsonify(
            {
                "status": "error",
                "message": "Worker ID does not match this worker.",
            }
        ), 403

    if not mt5_client.connected:
        return jsonify(
            {
                "status": "error",
                "message": "MT5 account is not connected.",
            }
        ), 409

    command = extract_request_data()

    result = command_executor.execute(command)

    status_code = 200 if result.success else 400

    return jsonify(
        {
            "status": "success" if result.success else "error",
            "success": result.success,
            "message": result.message,
            "command_type": result.command_type,
            "account_id": result.account_id,
            "worker_id": result.worker_id,
            "response": result.response,
        }
    ), status_code


if __name__ == "__main__":
    port = int(
        os.environ.get(
            "WORKER_PORT",
            "8080",
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
