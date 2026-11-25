from apps.api.app import create_app
from apps.api.config import Settings

def test_ea_permission_and_ack_flow():
    app=create_app(Settings(database_url="sqlite://",cors_origins="",agent_shared_secret="agent-secret"))
    c=app.test_client()
    r=c.post("/api/auth/register",json={"email":"ea@example.com","password":"long-password-123"})
    auth={"Authorization":"Bearer "+r.json["access_token"]}
    a=c.post("/api/accounts",headers=auth,json={"label":"Demo","login":"123","server":"Exness-MT5Trial","mt5_password":"demo-password"})
    account_id=a.json["account"]["id"]; ea_token=a.json["ea_token"]
    ea={"X-EA-Token":ea_token}
    assert c.get(f"/api/ea/permission?account_id={account_id}",headers=ea).json["entries_allowed"] is False
    c.post("/api/licences/activate",headers=auth,json={"code":"BOSSMODE01D"})
    c.post(f"/api/accounts/{account_id}/commands",headers=auth,json={"command":"START"})
    command=c.get(f"/api/ea/next?account_id={account_id}",headers=ea).json["command"]
    assert command["command"]=="START"
    assert c.get(f"/api/ea/permission?account_id={account_id}",headers=ea).json["entries_allowed"] is True
    ack=c.post("/api/ea/ack",headers=ea,json={"account_id":account_id,"command_id":command["id"],"result":{"applied":True}})
    assert ack.status_code==200
