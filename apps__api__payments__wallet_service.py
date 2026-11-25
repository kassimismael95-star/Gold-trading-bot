"""Append-only internal ledger. Provider balance is recorded separately."""
from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from ..extensions import db
from ..models import Wallet, WalletTransaction, Payment

def merchant_wallet(currency="USD"):
    wallet=Wallet.query.filter_by(owner_user_id=None,currency=currency).with_for_update().first()
    if wallet: return wallet
    wallet=Wallet(owner_user_id=None,currency=currency,ledger_balance=Decimal("0.00"))
    db.session.add(wallet)
    try: db.session.flush(); return wallet
    except IntegrityError:
        db.session.rollback()
        wallet=Wallet.query.filter_by(owner_user_id=None,currency=currency).with_for_update().first()
        if wallet:return wallet
        raise

def post_verified_payment(payment: Payment, provider_transaction_id: str):
    """Idempotently post only a payment already verified by the provider."""
    if payment.status!="SUCCESS" or not provider_transaction_id:
        raise ValueError("verified_successful_payment_required")
    wallet=merchant_wallet(payment.currency)
    existing=WalletTransaction.query.filter_by(payment_id=payment.id).first()
    if existing: return existing
    row=WalletTransaction(wallet_id=wallet.id,payment_id=payment.id,
        provider_transaction_id=str(provider_transaction_id),reference="payment:"+payment.tx_ref,
        amount=payment.amount,currency=payment.currency,kind="PAYMENT",status="POSTED",
        provider_confirmed_at=datetime.now(timezone.utc))
    wallet.ledger_balance=Decimal(wallet.ledger_balance or 0)+Decimal(payment.amount)
    db.session.add(row)
    try: db.session.commit(); return row
    except IntegrityError:
        db.session.rollback()
        existing=WalletTransaction.query.filter_by(payment_id=payment.id).first()
        if existing: return existing
        raise

def ledger_totals(currency="USD"):
    from datetime import datetime, timezone
    from ..models import Payment, PaymentRefund
    wallet=Wallet.query.filter_by(owner_user_id=None,currency=currency).first()
    rows=WalletTransaction.query.filter_by(currency=currency,kind="PAYMENT",status="POSTED").all()
    total=sum((Decimal(str(x.amount)) for x in rows),Decimal("0.00"))
    now=datetime.now(timezone.utc); today=now.date(); month=(now.year,now.month)
    payments=Payment.query.filter_by(currency=currency).all()
    successful=[p for p in payments if p.status=="SUCCESS"]
    today_income=sum((Decimal(str(p.amount)) for p in successful if p.created_at.date()==today),Decimal("0.00"))
    month_income=sum((Decimal(str(p.amount)) for p in successful if (p.created_at.year,p.created_at.month)==month),Decimal("0.00"))
    refunds=PaymentRefund.query.filter_by(currency=currency).all()
    refunded=sum((Decimal(str(r.amount)) for r in refunds if r.status in {"SUCCESS","COMPLETED","REFUNDED"}),Decimal("0.00"))
    return {"currency":currency,"ledger_balance":str(wallet.ledger_balance if wallet else Decimal("0.00")),
            "successful_income":str(total),"net_income":str(total-refunded),"today_income":str(today_income),"month_income":str(month_income),
            "pending_payments":Payment.query.filter_by(currency=currency,status="PENDING").count(),
            "failed_payments":Payment.query.filter_by(currency=currency,status="FAILED").count(),
            "refunded_amount":str(refunded)}

def post_completed_refund(refund):
    """Post a provider-confirmed refund once; never infer completion from request."""
    if str(refund.status).upper() not in {"COMPLETED", "REFUNDED", "SUCCESS"}:
        raise ValueError("completed_refund_required")
    reference=f"refund:{refund.provider_refund_id or refund.id}"
    existing=WalletTransaction.query.filter_by(reference=reference).first()
    if existing: return existing
    wallet=merchant_wallet(refund.currency)
    amount=Decimal(str(refund.amount))
    row=WalletTransaction(wallet_id=wallet.id,payment_id=None,
        provider_transaction_id=f"refund-{refund.provider_refund_id or refund.id}",
        reference=reference,amount=amount,currency=refund.currency,kind="REFUND",status="POSTED",
        provider_confirmed_at=datetime.now(timezone.utc))
    wallet.ledger_balance=Decimal(wallet.ledger_balance or 0)-amount
    db.session.add(row)
    try: db.session.commit(); return row
    except IntegrityError:
        db.session.rollback()
        existing=WalletTransaction.query.filter_by(reference=reference).first()
        if existing: return existing
        raise
