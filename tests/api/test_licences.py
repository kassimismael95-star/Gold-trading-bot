from datetime import datetime, timedelta, timezone
from apps.api.app import create_app
from apps.api.config import Settings
from apps.api.extensions import db
from apps.api.models import User, Entitlement

def client_and_user(email):
    app=create_app(Settings(database_url="sqlite://",cors_origins=""))
    c=app.test_client()
    r=c.post("/api/auth/register",json={"email":email,"password":"long-password-123"})
    return app,c,{"Authorization":"Bearer "+r.json["access_token"]}

def test_trial_first_and_second_after_cooldown():
    app,c,h=client_and_user("trial@example.com")
    assert c.post("/api/licences/activate",headers=h,json={"code":"BOSSMODE01D"}).status_code==201
    assert c.post("/api/licences/activate",headers=h,json={"code":"BOSSMODE01D"}).status_code==409
    with app.app_context():
        user=User.query.filter_by(email="trial@example.com").first()
        row=Entitlement.query.filter_by(user_id=user.id,code="BOSSMODE01D").first()
        row.expires_at=datetime.now(timezone.utc)-timedelta(hours=97)
        db.session.commit()
    assert c.post("/api/licences/activate",headers=h,json={"code":"BOSSMODE01D"}).status_code==201
    assert c.post("/api/licences/activate",headers=h,json={"code":"BOSSMODE01D"}).status_code==409

def test_vip_code_cannot_be_self_activated():
    app,c,h=client_and_user("vip@example.com")
    assert c.post("/api/licences/activate",headers=h,json={"code":"BOSSMODE98"}).status_code==403
