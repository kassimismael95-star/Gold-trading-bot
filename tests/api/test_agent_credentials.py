from apps.api.app import create_app
from apps.api.config import Settings
from apps.api.models import AccountCredential
from apps.api.extensions import db

def test_agent_only_retrieves_assigned_account_credential():
    app=create_app(Settings(database_url="sqlite://",cors_origins="",agent_shared_secret="agent-secret"))
    client=app.test_client()
    reg=client.post("/api/auth/register",json={"email":"vault@example.com","password":"long-password-123"})
    auth={"Authorization":"Bearer "+reg.json["access_token"]}
    account=client.post("/api/accounts",headers=auth,json={"label":"demo","login":"12345","server":"Demo-Server","mt5_password":"not-returned-password"})
    assert account.status_code==201
    account_id=account.json["account"]["id"]
    with app.app_context():
        stored=AccountCredential.query.filter_by(account_id=account_id).one()
        assert "not-returned-password" not in stored.password_ciphertext
    bootstrap={"X-Agent-Secret":"agent-secret"}
    enrolled=client.post("/api/agent/register",headers=bootstrap,json={"agent_id":"agent-a","hostname":"host-a"})
    assert enrolled.status_code==201
    per_agent={"X-Agent-ID":"agent-a","X-Agent-Secret":enrolled.json["agent_secret"]}
    heartbeat=client.post("/api/agent/heartbeat",headers=per_agent,json={"agent_id":"agent-a","hostname":"host-a"})
    assert heartbeat.status_code==200
    assignments=client.get("/api/agent/accounts?agent_id=agent-a",headers=per_agent)
    assert assignments.status_code==200
    assert [x["id"] for x in assignments.json["accounts"]]==[account_id]
    secret=client.get(f"/api/agent/accounts/{account_id}/credentials?agent_id=agent-a",headers=per_agent)
    assert secret.status_code==200
    assert secret.json["password"]=="not-returned-password"
    bootstrap_denied=client.get(f"/api/agent/accounts/{account_id}/credentials?agent_id=agent-a",headers=bootstrap)
    assert bootstrap_denied.status_code==401
    denied=client.get(f"/api/agent/accounts/{account_id}/credentials?agent_id=agent-b",headers=per_agent)
    assert denied.status_code==403
