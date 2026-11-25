from apps.api.app import create_app
from apps.api.config import Settings

def test_registration_and_demo_account():
    app=create_app(Settings(database_url="sqlite://",cors_origins=""))
    c=app.test_client()
    r=c.post("/api/auth/register",json={"email":"a@example.com","password":"long-password-123"})
    assert r.status_code==201
    token=r.json["access_token"]
    h={"Authorization":"Bearer "+token}
    r=c.post("/api/accounts",headers=h,json={"label":"Demo","login":"123","server":"Exness-MT5Trial","mt5_password":"demo-password"})
    assert r.status_code==201
    assert r.json["account"]["mode"]=="demo"

def test_live_account_locked():
    app=create_app(Settings(database_url="sqlite://",cors_origins=""))
    c=app.test_client()
    r=c.post("/api/auth/register",json={"email":"b@example.com","password":"long-password-123"})
    h={"Authorization":"Bearer "+r.json["access_token"]}
    out=c.post("/api/accounts",headers=h,json={"label":"Live","login":"1","server":"Exness","mt5_password":"demo-password","mode":"live"})
    assert out.status_code==403
