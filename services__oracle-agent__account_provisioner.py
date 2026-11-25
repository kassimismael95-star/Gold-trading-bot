"""Creates isolated per-account directories with restrictive permissions."""
import os,json,secrets
from pathlib import Path

def provision(workspace,account_id,config):
 if not str(account_id).isdigit(): raise ValueError("invalid_account_id")
 root=Path(workspace).resolve(); path=(root/str(account_id)).resolve()
 if root not in path.parents: raise ValueError("workspace_path_escape")
 path.mkdir(parents=True,exist_ok=True,mode=0o700); os.chmod(path,0o700)
 safe={k:v for k,v in config.items() if k not in {"password","mt5_password","token","secret"}}
 (path/"account.json").write_text(json.dumps(safe,indent=2)); os.chmod(path/"account.json",0o600)
 return str(path)
