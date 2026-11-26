from decimal import Decimal
from apps.api.app import create_app
from apps.api.config import Settings
from apps.api.payments import wallet_balance_sync as sync
from apps.api.models import WalletBalanceSnapshot

class FakeResponse:
    def raise_for_status(self): pass
    def json(self):
        return {"status":"success","data":[
            {"currency":"USD","available_balance":12.50,"ledger_balance":13.25},
            {"currency":"UGX","available_balance":5000,"ledger_balance":5000}]}

def test_fetch_and_record_provider_balances(monkeypatch):
    app=create_app(Settings(database_url="sqlite://",cors_origins="",flw_secret_key="test-secret"))
    monkeypatch.setattr(sync.requests,"get",lambda *a,**k:FakeResponse())
    with app.app_context():
        values=sync.read_flutterwave_balances()
        assert values["USD"]["ledger_balance"]==Decimal("13.25")
        snap,_=sync.record_provider_balance("USD",values["USD"]["ledger_balance"],values["USD"]["available_balance"])
        stored=WalletBalanceSnapshot.query.get(snap.id)
        assert stored.provider_balance==Decimal("13.25")
        assert stored.available_balance==Decimal("12.50")
