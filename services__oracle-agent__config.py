"""Validated agent configuration."""
import os
from pathlib import Path
class Config:
 api_base_url=os.environ.get("API_BASE_URL","").rstrip("/")
 agent_id=os.environ.get("AGENT_ID","")
 secret=os.environ.get("AGENT_SHARED_SECRET","")
 agent_secret=os.environ.get("AGENT_SECRET","")
 poll_seconds=max(3,int(os.environ.get("POLL_SECONDS","10")))
 workspace=os.path.abspath(os.environ.get("AGENT_WORKSPACE","/var/lib/gold-agent/accounts"))
 @classmethod
 def validate(cls):
  if not cls.api_base_url: raise RuntimeError("API_BASE_URL_required")
  if not cls.api_base_url.startswith("https://") and os.environ.get("APP_ENV")=="production": raise RuntimeError("production_agent_requires_https")
  stored_secret=Path(cls.workspace).resolve()/".agent-secret"
  if not cls.secret and not cls.agent_secret and not stored_secret.is_file(): raise RuntimeError("AGENT_SECRET_or_AGENT_SHARED_SECRET_required")
  if os.name!="nt" and not os.environ.get("MT5_LAUNCH_COMMAND"): raise RuntimeError("MT5_LAUNCH_COMMAND_required_on_Linux")
  return cls
