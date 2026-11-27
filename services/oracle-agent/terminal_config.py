
"""Create isolated MT5 startup files and GoldScalperEA inputs."""

import os
import re
from pathlib import Path

_AGENT_RE = re.compile(r"[A-Za-z0-9._-]{1,80}")
_SYMBOL_RE = re.compile(r"AUTO|[A-Za-z0-9._-]{1,40}")
_SERVER_RE = re.compile(r"[A-Za-z0-9 ._-]{1,120}")


def _safe_text(value, name):
    value = str(value)
    if "\r" in value or "\n" in value:
        raise ValueError(f"invalid_{name}")
    return value


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
    mode="demo",
):
    """Write a .set file matching GoldScalperEA.mq5 inputs.

    MQL5 ENUM_ACCOUNT_TRADE_MODE:
    DEMO=0, CONTEST=1, REAL=2.
    """
    api_url = _safe_text(api_url, "api_url").rstrip("/")
    if not api_url.startswith("https://"):
        raise ValueError("agent_api_url_must_use_https")
    if not _AGENT_RE.fullmatch(str(agent_id)):
        raise ValueError("invalid_agent_id")
    if not _SYMBOL_RE.fullmatch(str(symbol)):
        raise ValueError("invalid_symbol")
    if not str(token) or any(c in str(token) for c in "\r\n;="):
        raise ValueError("invalid_ea_token")

    try:
        account_id = int(account_id)
        magic = int(magic)
    except (TypeError, ValueError):
        raise ValueError("invalid_account_or_magic_number")

    if account_id <= 0:
        raise ValueError("invalid_account_id")
    if magic <= 0 or magic > 2147483647:
        raise ValueError("invalid_magic_number")

    mode = str(mode).strip().lower()
    if mode not in ("demo", "live"):
        raise ValueError("invalid_account_mode")

    # Live permission requires both a live account and backend authorization.
    # The customer must still separately issue START through the web platform.
    live_ok = mode == "live" and bool(allow_live_trading)
    required_mode = 2 if mode == "live" else 0

    values = {
        "InpApiBaseUrl": api_url,
        "InpAgentId": str(agent_id),
        "InpAccountId": str(account_id),
        "InpAccountToken": str(token),
        "InpRequiredAccountMode": str(required_mode),
        "InpSymbol": str(symbol),
        "InpMagic": str(magic),
        "InpAllowLiveTrading": str(live_ok).lower(),
        "InpConfirmRealMoneyTrading": str(live_ok).lower(),
        "InpStartEnabled": "false",
        "InpPollSeconds": "3",
        "InpMaxSlippagePoints": "30",
        "InpMaxPositionsOverride": "0",
        "InpOneEntryPerM1Bar": "false",
    }

    settings = risk_settings if isinstance(risk_settings, dict) else {}
    allowed = {"max_positions", "one_entry_per_m1_bar"}
    unsupported = set(settings) - allowed

    if unsupported:
        raise ValueError(
            "unsupported_ea_settings:" + ",".join(sorted(unsupported))
        )

    if "max_positions" in settings:
        value = settings["max_positions"]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 18
        ):
            raise ValueError("max_positions_must_be_integer_0_to_18")
        values["InpMaxPositionsOverride"] = str(value)

    if "one_entry_per_m1_bar" in settings:
        value = settings["one_entry_per_m1_bar"]
        if not isinstance(value, bool):
            raise ValueError("one_entry_per_m1_bar_must_be_boolean")
        values["InpOneEntryPerM1Bar"] = str(value).lower()

    for key, value in values.items():
        _safe_text(value, "ea_parameter_" + key)

    folder = Path(expert_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "GoldScalperEA.set"

    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
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
    password = _safe_text(
        password if password is not None else "",
        "password",
    )

    if not login.isdigit() or len(login) > 40:
        raise ValueError("invalid_mt5_login")
    if not _SERVER_RE.fullmatch(server):
        raise ValueError("invalid_mt5_server")
    if not password or len(password) > 512:
        raise ValueError("mt5_password_required")
    if not _SYMBOL_RE.fullmatch(symbol):
        raise ValueError("invalid_symbol")

    lines = [
        "[Common]",
        f"Login={login}",
        f"Password={password}",
        f"Server={server}",
        "",
        "[Experts]",
        "AllowLiveTrading=1",
        "AllowDllImport=0",
        "",
        "[StartUp]",
    ]

    if expert_path:
        expert_path = _safe_text(expert_path, "expert_path")
        lines.append("Expert=" + expert_path.replace("/", "\\"))

    if parameters_path:
        parameters_path = Path(parameters_path)
        lines.append("ExpertParameters=" + parameters_path.name)

    startup_symbol = "XAUUSD" if symbol == "AUTO" else symbol
    lines.extend([f"Symbol={startup_symbol}", "Period=M1", ""])

    folder = Path(account_dir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "terminal.transient.ini"

    path.write_text("\n".join(lines), encoding="utf-8")

    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    return path
