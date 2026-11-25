from apps.api.app import create_app
from apps.api.config import Settings

def test_account_risk_settings_are_server_validated_and_persisted():
    app=create_app(Settings(database_url="sqlite://",cors_origins=""))
    client=app.test_client()
    reg=client.post("/api/auth/register",json={"email":"risk@example.com","password":"long-password-123"})
    auth={"Authorization":"Bearer "+reg.json["access_token"]}
    created=client.post("/api/accounts",headers=auth,json={"label":"demo","login":"123","server":"Demo-Server","mt5_password":"secret"})
    account_id=created.json["account"]["id"]
    bad=client.post(f"/api/accounts/{account_id}/commands",headers=auth,json={"command":"SETTINGS","payload":{"max_positions":21}})
    assert bad.status_code==400
    good=client.post(f"/api/accounts/{account_id}/commands",headers=auth,json={"command":"SETTINGS","payload":{"max_positions":6,"news_filter_enabled":True}})
    assert good.status_code==202
    with app.app_context():
        from apps.api.models import TradingAccount
        row=TradingAccount.query.get(account_id)
        assert row.risk_settings["max_positions"]==6
        assert row.risk_settings["news_filter_enabled"] is True
        assert row.risk_settings["session_end_hour"]==24
