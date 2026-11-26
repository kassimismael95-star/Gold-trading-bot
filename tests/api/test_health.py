from apps.api.app import create_app
from apps.api.config import Settings

def test_health_live():
    app=create_app(Settings(database_url="sqlite://",cors_origins=""))
    c=app.test_client()
    assert c.get("/api/health/live").status_code==200
