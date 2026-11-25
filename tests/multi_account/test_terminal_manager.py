import importlib.util,subprocess,tempfile,os
from pathlib import Path
spec=importlib.util.spec_from_file_location("terminal_manager","services/oracle-agent/terminal_manager.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class Launcher:
 def launch(self,profile_dir,config_path):
  script=Path(profile_dir)/"terminal64.exe"
  return subprocess.Popen([str(script)],cwd=str(profile_dir),start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def test_terminal_pid_record_survives_manager_restart_and_stops_process_group():
 with tempfile.TemporaryDirectory() as temp:
  root=Path(temp);profile=root/"account"/"terminal";profile.mkdir(parents=True)
  script=profile/"terminal64.exe";script.write_text("#!/bin/sh\nsleep 60\n");script.chmod(0o755)
  config=profile/"terminal.ini";config.write_text("[Common]")
  first=module.TerminalManager(Launcher());first.bind(77,profile)
  proc=first.start(77,profile,config)
  assert first.status(77)=="RUNNING"
  second=module.TerminalManager(Launcher());second.bind(77,profile)
  assert second.status(77)=="RUNNING"
  second.stop(77,timeout=2)
  assert second.status(77)=="STOPPED"
  try:proc.wait(timeout=2)
  except Exception:pass
