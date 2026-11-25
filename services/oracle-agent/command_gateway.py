import requests
class CommandGateway:
    def __init__(self,api,secret,agent_id):
        self.api=api.rstrip("/"); self.agent_id=agent_id
        self.headers={"X-Agent-ID":agent_id,"X-Agent-Secret":secret,"Content-Type":"application/json"}
    def claim(self,account_id=None):
        r=requests.post(self.api+"/api/agent/commands/next",json={"agent_id":self.agent_id,"account_id":account_id},headers=self.headers,timeout=15)
        r.raise_for_status(); return r.json().get("command")
