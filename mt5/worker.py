"""
Windows MT5 execution worker.

Run this only on a Windows computer with MetaTrader 5 installed.
Do not deploy this file to Render.
"""

import os
import hmac
import time
import logging
from flask import Flask, request, jsonify

import MetaTrader5 as mt5


app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

ACTIVE_SESSIONS = {}


def get_worker_secret():
    secret = os.environ.get("WORKER_SHARED_SECRET")

    if not secret:
        raise RuntimeError("WORKER_SHARED_SECRET is required.")

    return secret


def verify_render_request():
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return False

    provided_token = auth_header.replace("Bearer ", "", 1)

    expected_token = get_worker_secret()

    return hmac.compare_digest(
        provided_token,
        expected_token
    )


def validate_command(command):
    required_fields = [
        "command_id",
        "user_id",
        "account_id",
        "bot_session_id",
        "command_type",
        "symbol"
    ]

    missing = [
        field
        for field in required_fields
        if not command.get(field)
    ]

    if missing:
        raise ValueError(
            f"Missing required fields: {', '.join(missing)}"
        )

    if command["command_type"] not in {
        "OPEN_POSITION",
        "CLOSE_POSITION",
        "CLOSE_BASKET",
        "MODIFY_POSITION"
    }:
        raise ValueError("Unsupported command type.")

    if command["command_type"] == "OPEN_POSITION":
        if command.get("direction") not in {"BUY", "SELL"}:
            raise ValueError("Direction must be BUY or SELL.")

        volume = command.get("volume")

        if not volume or float(volume) <= 0:
            raise ValueError("Volume must be greater than zero.")

    return True


def connect_mt5_session(
    account_id,
    login,
    password,
    server_name
):
    session_key = str(account_id)

    if session_key in ACTIVE_SESSIONS:
        return ACTIVE_SESSIONS[session_key]

    if not mt5.initialize():
        raise RuntimeError(
            f"MT5 initialization failed: {mt5.last_error()}"
        )

    if not mt5.login(
        login=int(login),
        password=password,
        server=server_name
    ):
        mt5.shutdown()

        raise RuntimeError(
            f"MT5 login failed: {mt5.last_error()}"
        )

    ACTIVE_SESSIONS[session_key] = {
        "account_id": account_id,
        "login": login,
        "server_name": server_name,
        "connected_at": time.time()
    }

    return ACTIVE_SESSIONS[session_key]


def disconnect_mt5_session(account_id):
    session_key = str(account_id)

    if session_key in ACTIVE_SESSIONS:
        mt5.shutdown()

        del ACTIVE_SESSIONS[session_key]


def get_current_quote(symbol):
    quote = mt5.symbol_info_tick(symbol)

    if not quote:
        raise ValueError(f"No live quote available for {symbol}.")

    return quote


def execute_open_position(command):
    symbol = command["symbol"]
    direction = command["direction"]
    volume = float(command["volume"])

    quote = get_current_quote(symbol)

    if direction == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        price = quote.ask

    else:
        order_type = mt5.ORDER_TYPE_SELL
        price = quote.bid

    request_payload = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": float(command["stop_loss"]) if command.get("stop_loss") else 0.0,
        "tp": float(command["take_profit"]) if command.get("take_profit") else 0.0,
        "deviation": 20,
        "magic": 987654,
        "comment": f"BOSSMODE-{command['command_id']}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC
    }

    result = mt5.order_send(request_payload)

    if result is None:
        raise RuntimeError(
            f"MT5 order_send failed: {mt5.last_error()}"
        )

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        raise RuntimeError(
            f"MT5 order rejected: {result.retcode} {result.comment}"
        )

    return {
        "status": "EXECUTED",
        "ticket": result.order,
        "price": result.price,
        "volume": volume
    }


def execute_close_position(command):
    symbol = command["symbol"]
    ticket = command.get("ticket")

    if not ticket:
        raise ValueError("Ticket is required to close a position.")

    positions = mt5.positions_get(ticket=int(ticket))

    if not positions:
        raise ValueError(f"Position {ticket} was not found.")

    position = positions[0]

    if position.type == mt5.POSITION_TYPE_BUY:
        order_type = mt5.ORDER_TYPE_SELL
        price = mt5.symbol_info_tick(symbol).bid

    else:
        order_type = mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(symbol).ask

    request_payload = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": int(ticket),
        "symbol": symbol,
        "volume": position.volume,
        "type": order_type,
        "price": price,
        "deviation": 20,
        "magic": 987654,
        "comment": f"CLOSE-{command['command_id']}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC
    }

    result = mt5.order_send(request_payload)

    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        raise RuntimeError(
            f"MT5 close failed: {mt5.last_error()} {result.comment if result else ''}"
        )

    return {
        "status": "EXECUTED",
        "ticket": ticket,
        "close_price": result.price
    }


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "worker": "MT5"
    })


@app.route("/execute-command", methods=["POST"])
def execute_command():
    if not verify_render_request():
        return jsonify({
            "error": "Unauthorized worker request."
        }), 401

    command = request.get_json(silent=True) or {}

    try:
        validate_command(command)

        account_id = command["account_id"]

        login = os.environ.get("MT5_LOGIN")
        password = os.environ.get("MT5_PASSWORD")
        server_name = os.environ.get("MT5_SERVER")

        if not login or not password or not server_name:
            raise RuntimeError(
                "MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER are required."
            )

        connect_mt5_session(
            account_id,
            login,
            password,
            server_name
        )

        if command["command_type"] == "OPEN_POSITION":
            result = execute_open_position(command)

        elif command["command_type"] == "CLOSE_POSITION":
            result = execute_close_position(command)

        else:
            raise ValueError(
                "This command type is not enabled in the worker yet."
            )

        return jsonify({
            "command_id": command["command_id"],
            "result": result
        })

    except Exception as error:
        logging.exception("Command execution failed.")

        return jsonify({
            "command_id": command.get("command_id"),
            "error": str(error)
        }), 400


if __name__ == "__main__":
    port = int(os.environ.get("WORKER_PORT", 8000))

    app.run(
        host="0.0.0.0",
        port=port
  )
