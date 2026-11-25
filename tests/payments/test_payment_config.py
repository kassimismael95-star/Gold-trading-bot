from apps.api.payments.flutterwave import PLANS

def test_plan_amounts():
    assert str(PLANS["PLAN_15D"][0])=="25.00"
    assert PLANS["PLAN_33D"][1]==33
    assert PLANS["PLAN_70D"][1]==70
