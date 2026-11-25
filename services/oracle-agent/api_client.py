"""Authenticated Oracle API client; per-agent secret is memory-only in requests."""
import os, hashlib, requests
from pathlib import Path

class APIClient:
    def __init__(self, base_url, bootstrap_secret="", timeout=15):
        self.base_url=base_url.rstrip("/").rstrip("/")
        self.session=requests.Session()
        self.session.headers.update({"Content-Type":"application/json"})
        self.bootstrap_secret=bootstrap_secret
        self.timeout=timeout
        self.agent_id=None

    def _request(self,method,path,**kwargs):
        response=self.session.request(method,self.base_url+path,timeout=self.timeout,**kwargs)
        response.raise_for_status(); return response.json()

    def ensure_agent_secret(self,agent_id,workspace,bootstrap_secret,configured_secret=""):
        self.agent_id=agent_id
        secret=configured_secret.strip()
        secret_path=Path(workspace).resolve()/".agent-secret"
        if not secret and secret_path.is_file():
            secret=secret_path.read_text(encoding="utf-8").strip()
        if not secret:
            if not bootstrap_secret: raise RuntimeError("AGENT_SECRET_or_bootstrap_AGENT_SHARED_SECRET_required")
            bootstrap=requests.Session(); bootstrap.headers.update({"X-Agent-Secret":bootstrap_secret,"Content-Type":"application/json"})
            response=bootstrap.post(self.base_url+"/api/agent/register",json={"agent_id":agent_id,"hostname":__import__("socket").gethostname()},timeout=self.timeout)
            response.raise_for_status(); secret=response.json().get("agent_secret","")
            if not secret: raise RuntimeError("agent_enrollment_did_not_return_secret")
            secret_path.parent.mkdir(parents=True,exist_ok=True)
            fd=os.open(str(secret_path),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,"w",encoding="utf-8") as handle: handle.write(secret)
            try: os.chmod(secret_path,0o600)
            except OSError: pass
        self.session.headers.update({"X-Agent-ID":agent_id,"X-Agent-Secret":secret})
        return True

    def heartbeat(self,agent_id,hostname,metrics=None):
        return self._request("POST","/api/agent/heartbeat",json={"agent_id":agent_id,"hostname":hostname,"metrics":metrics or {}})
    def accounts(self,agent_id):
        return self._request("GET","/api/agent/accounts",params={"agent_id":agent_id}).get("accounts",[])
    def credentials(self,agent_id,account_id):
        return self._request("GET",f"/api/agent/accounts/{int(account_id)}/credentials",params={"agent_id":agent_id})
