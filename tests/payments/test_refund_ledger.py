from datetime import datetime,timezone,timedelta
from decimal import Decimal
from apps.api.app import create_app
from apps.api.config import Settings
from apps.api.extensions import db
from apps.api.models import User,Payment,PaymentRefund,Subscription,Entitlement,Wallet,WalletTransaction
from apps.api.payments.wallet_service import post_verified_payment,post_completed_refund
from apps.api.payments.refund_service import apply_completed_refund_policy

def test_refund_ledger_is_idempotent_and_full_refund_revokes_paid_access():
    app=create_app(Settings(database_url="sqlite://",cors_origins=""))
    with app.app_context():
        user=User(email="refund@example.com");user.set_password("long-password-123");db.session.add(user);db.session.flush()
        now=datetime.now(timezone.utc)
        payment=Payment(user_id=user.id,tx_ref="refund-ref",plan_code="PLAN_15D",amount=Decimal("25.00"),currency="USD",status="SUCCESS",provider_id="tx-100")
        db.session.add(payment);db.session.flush()
        subscription=Subscription(user_id=user.id,payment_id=payment.id,plan_code=payment.plan_code,status="ACTIVE",starts_at=now,expires_at=now+timedelta(days=15))
        entitlement=Entitlement(user_id=user.id,code="BOSSMODE30D",status="ACTIVE",expires_at=subscription.expires_at)
        db.session.add_all([subscription,entitlement]);db.session.commit()
        post_verified_payment(payment,"tx-100")
        refund=PaymentRefund(payment_id=payment.id,provider_refund_id="rf-100",amount=Decimal("25.00"),currency="USD",status="COMPLETED")
        db.session.add(refund);db.session.commit()
        post_completed_refund(refund);post_completed_refund(refund)
        apply_completed_refund_policy(payment)
        wallet=Wallet.query.filter_by(owner_user_id=None,currency="USD").one()
        assert wallet.ledger_balance==Decimal("0.00")
        assert WalletTransaction.query.filter_by(kind="REFUND").count()==1
        assert subscription.status=="REFUNDED"
        assert entitlement.status=="REVOKED"
