from apps.api.app import create_app
from apps.api.config import Settings

def test_live_account_creation_is_operator_gated():
    app=create_app(Settings(database_url="sqlite://",cors_origins="",allow_live_trading=False))
    client=app.test_client()
    user=client.post("/api/auth/register",json={"email":"live-off@example.com","password":"long-password-123"})
    auth={"Authorization":"Bearer "+user.json["access_token"]}
    response=client.post("/api/accounts",headers=auth,json={"label":"live","login":"123","server":"Broker-Live","mt5_password":"secret","mode":"live"})
    assert response.status_code==403

    app2=create_app(Settings(database_url="sqlite://",cors_origins="",allow_live_trading=True))
    client2=app2.test_client()
    user2=client2.post("/api/auth/register",json={"email":"live-on@example.com","password":"long-password-123"})
    auth2={"Authorization":"Bearer "+user2.json["access_token"]}
    response2=client2.post("/api/accounts",headers=auth2,json={"label":"live","login":"456","server":"Broker-Live","mt5_password":"secret","mode":"live"})
    assert response2.status_code==201
