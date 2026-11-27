
"""Generate isolated MT5 startup and EA configuration files."""

import os
import re
from pathlib import Path


def write_ea_set(
    expert_dir,
    api_url,
    agent_id,
    account_id,
    token,
    symbol="AUTO",
    magic=9924102,
    risk_settings=None,
    allow_live_trading=False,
):
    if not str(api_url).startswith("https://"):
        raise ValueError("agent_api_url_must_use_https")

    if not re.fullmatch(
        r"[A-Za-z0-9._-]{1,80}",
        str(agent_id)
    ):
        raise ValueError("invalid_agent_id")

    if not str(token) or any(
        character in str(token)
        for character in "\r\n;="
    ):
        raise ValueError("invalid_ea_token")

    if not re.fullmatch(
        r"AUTO|[A-Za-z0-9._-]{1,40}",
        str(symbol)
    ):
        raise ValueError("invalid_symbol")

    if int(account_id) <= 0:
        raise ValueError("invalid_account_id")

    if int(magic) <= 0 or int(magic) > 2147483647:
        raise ValueError("invalid_magic_number")

    # The caller only sets this flag when the account is live
    # and the backend's global live-trading switch permits it.
    live_authorized = bool(allow_live_trading)

    folder = Path(expert_dir)
    folder.mkdir(parents=True, exist_ok=True)

    values = {
        "InpApiBaseUrl": str(api_url).rstrip("/"),
        "InpAgentId": str(agent_id),
        "InpAccountId": str(int(account_id)),
        "InpAccountToken": str(token),
        "InpSymbol": str(symbol),
        "InpMagic": str(int(magic)),

        # The EA must also check the backend permission endpoint.
        "InpAllowLiveTrading": str(live_authorized).lower(),
        "InpConfirmRealMoneyTrading": str(live_authorized).lower(),

        # Never automatically begin trading after provisioning.
        "InpStartEnabled": "false",

        "InpPollSeconds": "3",
        "InpMaxSlippagePoints": "30",

        # No automatic basket close or fixed drawdown shutdown.
        "InpBasketProfitTargetUSD": "0",
        "InpBasketLossLimitUSD": "0",
        "InpMaxDrawdownPercent": "0",

        "InpMaxPositionsOverride": "0",
        "InpOneEntryPerM1Bar": "false",

        # Preserve the original entry strategy's normal operation.
        "InpNewsFilterEnabled": "false",
        "InpNewsMinutesBefore": "15",
        "InpNewsMinutesAfter": "15",
        "InpSessionFilterEnabled": "false",
        "InpSessionStartHour": "0",
        "InpSessionEndHour": "24",
        "InpRequireCandleConfirmation": "true",
    }

    settings = (
        risk_settings
        if isinstance(risk_settings, dict)
        else {}
    )

    allowed_settings = {
        "max_positions",
        "one_entry_per_m1_bar",
    }

    unsupported = set(settings) - allowed_settings

    if unsupported:
        raise ValueError(
            "unsupported_risk_settings:"
            + ",".join(sorted(unsupported))
        )

    if "max_positions" in settings:
        value = settings["max_positions"]

        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            or value > 18
        ):
            raise ValueError(
                "max_positions_must_be_integer_0_to_18"
            )

        values["InpMaxPositionsOverride"] = str(value)

    if "one_entry_per_m1_bar" in settings:
        value = settings["one_entry_per_m1_bar"]

        if not isinstance(value, bool):
            raise ValueError(
                "one_entry_per_m1_bar_must_be_boolean"
            )

        values["InpOneEntryPerM1Bar"] = str(value).lower()

    for key, value in values.items():
        if any(character in str(value) for character in "\r\n"):
            raise ValueError(
                "invalid_ea_parameter:" + key
            )

    path = folder / "GoldScalperEA.set"

    content = "\n".join(
        f"{key}={value}"
        for key, value in values.items()
    ) + "\n"

    path.write_text(
        content,
        encoding="utf-8"
    )

    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    return path


def write_config(
    account_dir,
    login,
    server,
    symbol="AUTO",
    password=None,
    expert_path=None,
    parameters_path=None,
):
    login = str(login).strip()
    server = str(server).strip()
    symbol = str(symbol).strip()

    if not login.isdigit() or len(login) > 40:
        raise ValueError("invalid_mt5_login")

    if not re.fullmatch(
        r"[A-Za-z0-9 ._-]{1,120}",
        server
    ):
        raise ValueError("invalid_mt5_server")

    if password is None or not str(password):
        raise ValueError("mt5_password_required")

    password = str(password)

    if "\r" in password or "\n" in password:
        raise ValueError("invalid_mt5_password_characters")

    if not re.fullmatch(
        r"AUTO|[A-Za-z0-9._-]{1,40}",
        symbol
    ):
        raise ValueError("invalid_symbol")

    lines = [
        "[Common]",
        f"Login={login}",
        f"Password={password}",
        f"Server={server}",

        "[Experts]",
        "AllowLiveTrading=1",
        "AllowDllImport=0",

        "[StartUp]",
    ]

    if expert_path:
        expert_path = str(expert_path)

        if any(character in expert_path for character in "\r\n"):
            raise ValueError("invalid_expert_path")

        lines.append(
            "Expert=" + expert_path.replace("/", "\\")
        )

    if parameters_path:
        parameters_path = Path(parameters_path)

        if any(
            character in str(parameters_path)
            for character in "\r\n"
        ):
            raise ValueError("invalid_parameters_path")

        lines.append(
            "ExpertParameters=" + parameters_path.name
        )

    startup_symbol = (
        "XAUUSD"
        if not symbol or symbol == "AUTO"
        else symbol
    )

    lines.extend([
        f"Symbol={startup_symbol}",
        "Period=M1",
    ])

    directory = Path(account_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)

    path = directory / "terminal.transient.ini"

    path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8"
    )

    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    return path
