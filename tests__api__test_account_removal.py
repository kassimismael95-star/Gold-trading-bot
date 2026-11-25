from datetime import datetime,timezone
from apps.api.app import create_app
from apps.api.config import Settings
from apps.api.extensions import db
from apps.api.models import TradingAccount,AccountCredential,AccountTelemetry

def test_account_removal_keeps_assigned_ea_until_connected_and_flat():
    app=create_app(Settings(database_url="sqlite://",cors_origins="",agent_shared_secret="agent-secret"))
    client=app.test_client()
    registered=client.post("/api/auth/register",json={"email":"remove@example.com","password":"long-password-123"})
    user_headers={"Authorization":"Bearer "+registered.json["access_token"]}
    created=client.post("/api/accounts",headers=user_headers,json={"label":"demo","login":"123","server":"Demo-Server","mt5_password":"secret"})
    account_id=created.json["account"]["id"];ea_token=created.json["ea_token"]
    enrolled=client.post("/api/agent/register",headers={"X-Agent-Secret":"agent-secret"},json={"agent_id":"agent-a","hostname":"host-a"})
    agent_headers={"X-Agent-ID":"agent-a","X-Agent-Secret":enrolled.json["agent_secret"]}
    with app.app_context():
        account=TradingAccount.query.get(account_id);account.agent_id="agent-a"
        db.session.add(AccountTelemetry(account_id=account_id,connected_to_broker=True,open_positions_count=2,updated_at=datetime.now(timezone.utc)))
        db.session.commit()
    deleted=client.delete(f"/api/accounts/{account_id}",headers=user_headers)
    assert deleted.status_code==202 and deleted.json["removal_pending"] is True
    permission=client.get(f"/api/ea/permission?account_id={account_id}",headers={"X-EA-Token":ea_token})
    assert permission.status_code==200 and permission.json["entries_allowed"] is False
    assigned=client.get("/api/agent/accounts?agent_id=agent-a",headers=agent_headers)
    assert assigned.status_code==200 and assigned.json["accounts"][0]["is_deleted"] is True
    with app.app_context():
        telemetry=AccountTelemetry.query.filter_by(account_id=account_id).first()
        telemetry.open_positions_count=0;telemetry.connected_to_broker=True;telemetry.updated_at=datetime.now(timezone.utc)
        db.session.commit()
    cleanup=client.get("/api/agent/accounts?agent_id=agent-a",headers=agent_headers)
    assert cleanup.status_code==200 and cleanup.json["accounts"]==[]
    with app.app_context():
        account=TradingAccount.query.get(account_id);credential=AccountCredential.query.filter_by(account_id=account_id).first()
        assert account.agent_id is None and credential.revoked is True
