import importlib.util
import os
import stat
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("terminal_config", "services/oracle-agent/terminal_config.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_startup_config_is_restricted_and_transient():
    with tempfile.TemporaryDirectory() as root:
        path = Path(module.write_config(root, "123456", "Broker-Demo", password="demo-secret"))
        assert path.name == "terminal.transient.ini"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert "demo-secret" in path.read_text()

def test_ea_parameters_are_account_scoped_and_restricted():
    with tempfile.TemporaryDirectory() as root:
        path = Path(module.write_ea_set(root, "https://api.example.test", "agent-1", 42, "one-time-token", "XAUUSDm"))
        text = path.read_text()
        assert "InpAccountId=42" in text
        assert "InpAccountToken=one-time-token" in text
        assert "InpAllowLiveTrading=false" in text
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

def test_ea_parameter_rejects_newline_injection():
    with tempfile.TemporaryDirectory() as root:
        try:
            module.write_ea_set(root, "https://api.example.test", "agent\nInpAllowLiveTrading=true", 42, "token")
        except ValueError:
            pass
        else:
            raise AssertionError("newline injection must be rejected")

def test_terminal_launcher_requires_isolated_config_and_prefix():
 import importlib.util
 spec2=importlib.util.spec_from_file_location("terminal_launcher","services/oracle-agent/terminal_launcher.py")
 launcher_module=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(launcher_module)
 with tempfile.TemporaryDirectory() as root:
  root=Path(root); (root/"terminal64.exe").write_bytes(b"fake")
  launcher=launcher_module.TerminalLauncher(root,"echo")
  config=root/"terminal.transient.ini";config.write_text("[Common]")
  command=launcher.build_command(root,config)
  assert command[0]=="echo" and str(root/"terminal64.exe") in command
  try: launcher.build_command(root,root.parent/"outside.ini")
  except ValueError: pass
  else: raise AssertionError("config path must remain inside account terminal")

def test_terminal_config_rejects_credential_and_symbol_injection():
 with tempfile.TemporaryDirectory() as root:
  for password,symbol in [("pass\nLogin=999","XAUUSD"),("pass","XAUUSD\nPeriod=H1")]:
   try: module.write_config(root,"123","Demo-Server",symbol,password=password)
   except ValueError: pass
   else: raise AssertionError("config injection must be rejected")

def test_account_risk_settings_are_written_to_ea_parameters():
 with tempfile.TemporaryDirectory() as root:
  settings={"max_positions":6,"news_filter_enabled":True,"news_minutes_before":20,"session_filter_enabled":True,"session_start_hour":8,"session_end_hour":18}
  path=module.write_ea_set(root,"https://api.example.test","agent-1",42,"one-time-token","XAUUSDm",risk_settings=settings)
  text=Path(path).read_text()
  assert "InpMaxPositionsOverride=6" in text
  assert "InpNewsFilterEnabled=true" in text
  assert "InpNewsMinutesBefore=20" in text
  assert "InpSessionFilterEnabled=true" in text
  assert "InpSessionStartHour=8" in text
  assert "InpSessionEndHour=18" in text

def test_live_trading_flag_requires_explicit_agent_configuration():
 with tempfile.TemporaryDirectory() as root:
  demo=Path(module.write_ea_set(root,"https://api.example.test","agent-1",42,"demo-token"))
  assert "InpAllowLiveTrading=false" in demo.read_text()
  live=Path(module.write_ea_set(root,"https://api.example.test","agent-1",42,"live-token",allow_live_trading=True))
  assert "InpAllowLiveTrading=true" in live.read_text()
