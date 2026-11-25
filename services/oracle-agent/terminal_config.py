"""Generate mode-0600 transient MT5 startup and EA input files."""
import os,re
from pathlib import Path

def write_ea_set(expert_dir, api_url, agent_id, account_id, token, symbol="AUTO", magic=9924102, risk_settings=None, allow_live_trading=False):
    if not str(api_url).startswith("https://"):
        raise ValueError("agent_api_url_must_use_https")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}",str(agent_id)):
        raise ValueError("invalid_agent_id")
    if not str(token) or any(c in str(token) for c in "\r\n;="):
        raise ValueError("invalid_ea_token")
    if not re.fullmatch(r"AUTO|[A-Za-z0-9._-]{1,40}",str(symbol)):
        raise ValueError("invalid_symbol")
    if int(account_id)<=0:raise ValueError("invalid_account_id")
    if int(magic)<=0 or int(magic)>2147483647:raise ValueError("invalid_magic_number")
    folder=Path(expert_dir); folder.mkdir(parents=True,exist_ok=True)
    values={"InpApiBaseUrl":str(api_url).rstrip("/"),"InpAgentId":agent_id,"InpAccountId":str(account_id),
            "InpAccountToken":token,"InpSymbol":symbol,"InpMagic":str(magic),
            "InpAllowLiveTrading":str(bool(allow_live_trading)).lower(),"InpStartEnabled":"false",
            "InpPollSeconds":"3","InpMaxSlippagePoints":"30",
            "InpBasketProfitTargetUSD":"5.0","InpBasketLossLimitUSD":"20.0",
            "InpMaxDrawdownPercent":"35.0","InpMaxPositionsOverride":"0","InpOneEntryPerM1Bar":"false",
            "InpNewsFilterEnabled":"false","InpNewsMinutesBefore":"15","InpNewsMinutesAfter":"15",
            "InpSessionFilterEnabled":"false","InpSessionStartHour":"0","InpSessionEndHour":"24",
            "InpRequireCandleConfirmation":"true"}
    settings=risk_settings if isinstance(risk_settings,dict) else {}
    mapping={"basket_profit_target_usd":"InpBasketProfitTargetUSD","basket_loss_limit_usd":"InpBasketLossLimitUSD",
      "max_drawdown_percent":"InpMaxDrawdownPercent","max_positions":"InpMaxPositionsOverride",
      "one_entry_per_m1_bar":"InpOneEntryPerM1Bar","news_filter_enabled":"InpNewsFilterEnabled",
      "news_minutes_before":"InpNewsMinutesBefore","news_minutes_after":"InpNewsMinutesAfter",
      "session_filter_enabled":"InpSessionFilterEnabled","session_start_hour":"InpSessionStartHour",
      "session_end_hour":"InpSessionEndHour","require_candle_confirmation":"InpRequireCandleConfirmation"}
    bounds={"max_positions":(0,20),"basket_profit_target_usd":(0,1000),"basket_loss_limit_usd":(1,10000),
      "max_drawdown_percent":(1,35),"news_minutes_before":(0,240),"news_minutes_after":(0,240),
      "session_start_hour":(0,23),"session_end_hour":(1,24)}
    bool_keys={"one_entry_per_m1_bar","news_filter_enabled","session_filter_enabled","require_candle_confirmation"}
    for key,value in settings.items():
        target=mapping.get(key)
        if not target:continue
        if key in bool_keys:
            if not isinstance(value,bool):raise ValueError("invalid_ea_boolean_setting")
            values[target]=str(value).lower()
        elif key in bounds:
            number=float(value);low,high=bounds[key]
            if not number==number or number<low or number>high:raise ValueError("invalid_ea_numeric_setting")
            if key in {"max_positions","news_minutes_before","news_minutes_after","session_start_hour","session_end_hour"} and int(number)!=number:raise ValueError("invalid_ea_integer_setting")
            values[target]=str(int(number)) if int(number)==number else str(number)
    if any("\n" in str(v) or "\r" in str(v) for v in values.values()):
        raise ValueError("invalid_ea_parameter")
    path=folder/"GoldScalperEA.set"
    path.write_text("\n".join(f"{k}={v}" for k,v in values.items())+"\n")
    os.chmod(path,0o600)
    return path

def write_config(account_dir,login,server,symbol="AUTO",password=None,expert_path=None,parameters_path=None):
    if not str(login).isdigit() or len(str(login))>40: raise ValueError("invalid_mt5_login")
    if not re.fullmatch(r"[A-Za-z0-9 ._-]{1,120}",str(server).strip()):
        raise ValueError("invalid_mt5_server")
    if password is None or not str(password): raise ValueError("mt5_password_required")
    if "\r" in str(password) or "\n" in str(password): raise ValueError("invalid_mt5_password_characters")
    safe_password=str(password)
    safe_server=str(server).replace("\r","").replace("\n","")
    if not re.fullmatch(r"AUTO|[A-Za-z0-9._-]{1,40}",str(symbol)): raise ValueError("invalid_symbol")
    lines=["[Common]",f"Login={login}",f"Password={safe_password}",f"Server={safe_server}",
           "[Experts]","AllowLiveTrading=1","AllowDllImport=0","[StartUp]"]
    if expert_path:
        if any(c in str(expert_path) for c in "\r\n"):raise ValueError("invalid_expert_path")
        lines.append(f"Expert={expert_path.replace('/', chr(92))}")
    if parameters_path:
        if any(c in str(parameters_path) for c in "\r\n"):raise ValueError("invalid_parameters_path")
        lines.append(f"ExpertParameters={Path(parameters_path).name}")
    lines.extend([f"Symbol={symbol if symbol and symbol!='AUTO' else 'XAUUSD'}","Period=M1"])
    path=Path(account_dir)/"terminal.transient.ini"
    path.write_text("\n".join(lines)+"\n"); os.chmod(path,0o600)
    return path
