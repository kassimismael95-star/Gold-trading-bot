import pytest
from apps.api.app import create_app
from apps.api.config import Settings
from apps.api.extensions import db
from apps.api.models import User,Payment
from apps.api.payments import transaction_verifier as verifier

class Response:
    def __init__(self,data):self.data=data
    def raise_for_status(self):pass
    def json(self):return {"status":"success","data":self.data}

def test_verified_payment_binds_id_reference_amount_currency_and_customer(monkeypatch):
    app=create_app(Settings(database_url="sqlite://",cors_origins="",flw_secret_key="test-secret"))
    with app.app_context():
        user=User(email="pay@example.com");user.set_password("long-password-123");db.session.add(user);db.session.flush()
        payment=Payment(user_id=user.id,tx_ref="gold-ref",plan_code="PLAN_15D",amount="25.00",currency="USD",status="PENDING")
        db.session.add(payment);db.session.commit()
        good={"id":123,"tx_ref":"gold-ref","status":"successful","amount":"25.00","currency":"USD","customer":{"email":"pay@example.com"}}
        monkeypatch.setattr(verifier.requests,"get",lambda *a,**k:Response(good))
        assert verifier.verify_transaction("123",payment)["status"]=="successful"
        bad={**good,"amount":"26.00"}
        monkeypatch.setattr(verifier.requests,"get",lambda *a,**k:Response(bad))
        with pytest.raises(ValueError,match="amount_mismatch"):
            verifier.verify_transaction("123",payment)
