"""Reconciliation utilities for matching provider transactions and ledger entries."""
from decimal import Decimal
from ..models import Payment, WalletTransaction

def reconcile_payment(tx_ref, provider_transaction_id, amount, currency):
    payment=Payment.query.filter_by(tx_ref=tx_ref).first()
    if not payment: return {"status":"UNMATCHED","reason":"unknown_reference"}
    if str(payment.provider_id or "")!=str(provider_transaction_id): return {"status":"UNMATCHED","reason":"provider_id_mismatch"}
    if Decimal(str(payment.amount))!=Decimal(str(amount)) or payment.currency!=str(currency).upper():
        return {"status":"UNMATCHED","reason":"amount_or_currency_mismatch"}
    ledger=WalletTransaction.query.filter_by(payment_id=payment.id).first()
    return {"status":"MATCHED" if ledger else "LEDGER_MISSING","payment_id":payment.id}
