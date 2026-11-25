from apps.api.app import create_app
from apps.api.config import Settings

def test_user_cannot_read_another_users_account():
    app=create_app(Settings(database_url="sqlite://",cors_origins=""))
    c=app.test_client()
    a=c.post("/api/auth/register",json={"email":"one@example.com","password":"long-password-123"}).json["access_token"]
    b=c.post("/api/auth/register",json={"email":"two@example.com","password":"long-password-123"}).json["access_token"]
    account=c.post("/api/accounts",headers={"Authorization":"Bearer "+a},json={"label":"demo","login":"1","server":"s","mt5_password":"demo-password"}).json["account"]["id"]
    res=c.get(f"/api/accounts/{account}/status",headers={"Authorization":"Bearer "+b})
    assert res.status_code==404
