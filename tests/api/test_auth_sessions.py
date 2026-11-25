from apps.api.app import create_app
from apps.api.config import Settings

def test_refresh_and_logout_revokes_access_and_refresh():
    app=create_app(Settings(database_url="sqlite://",cors_origins=""))
    client=app.test_client()
    registered=client.post("/api/auth/register",json={"email":"session@example.com","password":"long-password-123"})
    assert registered.status_code==201
    access=registered.json["access_token"]
    refresh=registered.json["refresh_token"]
    refreshed=client.post("/api/auth/refresh",headers={"Authorization":"Bearer "+refresh},json={})
    assert refreshed.status_code==200
    logout=client.post("/api/auth/logout",headers={"Authorization":"Bearer "+access},json={"refresh_token":refresh})
    assert logout.status_code==200
    assert client.post("/api/auth/refresh",headers={"Authorization":"Bearer "+refresh},json={}).status_code==401
    assert client.get("/api/accounts",headers={"Authorization":"Bearer "+access}).status_code==401
