
import hmac

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required

from ..security import current_user
from .flutterwave import initialize_payment, verify_and_activate


bp = Blueprint("payments", __name__, url_prefix="/api/payments")


@bp.post("/flutterwave/initialize")
@jwt_required()
def initialize():
    data = request.get_json(silent=True) or {}

    try:
        payment, checkout_url = initialize_payment(
            current_user(),
            str(data.get("plan_code", "")),
            str(data.get("currency", "USD")).upper(),
        )

        return jsonify(
            tx_ref=payment.tx_ref,
            checkout_url=checkout_url,
        ), 201

    except (ValueError, RuntimeError) as exc:
        return jsonify(error=str(exc)), 400

    except Exception:
        current_app.logger.exception(
            "Payment initialization failed"
        )
        return jsonify(
            error="payment_initialization_failed"
        ), 502


@bp.post("/flutterwave/webhook")
def webhook():
    supplied = request.headers.get("verif-hash", "")
    expected = current_app.config.get(
        "FLW_WEBHOOK_HASH", ""
    )

    if not expected or not hmac.compare_digest(
        supplied, expected
    ):
        return jsonify(
            error="invalid_webhook_signature"
        ), 401

    payload = request.get_json(silent=True) or {}

    if not isinstance(payload, dict):
        return jsonify(
            error="invalid_webhook_payload"
        ), 400

    data = payload.get("data") or {}

    if not isinstance(data, dict):
        return jsonify(
            error="invalid_webhook_data"
        ), 400

    if (
        payload.get("event") != "charge.completed"
        or data.get("status") != "successful"
    ):
        return jsonify(ok=True, ignored=True)

    try:
        from .webhook_service import accept_completed_event

        event, created = accept_completed_event(payload)

        # Duplicate provider deliveries must not repeat
        # payment activation.
        if event.processed:
            return jsonify(
                ok=True,
                duplicate=True,
            )

        verify_and_activate(
            str(data.get("tx_ref", "")),
            str(data.get("id", "")),
        )

        event.processed = True

        from ..extensions import db

        db.session.commit()

        return jsonify(ok=True)

    except Exception:
        current_app.logger.exception(
            "Payment webhook verification failed"
        )

        from ..extensions import db

        db.session.rollback()

        return jsonify(
            error="verification_failed"
        ), 400


@bp.post("/flutterwave/refund-webhook")
def refund_webhook():
    supplied = request.headers.get("verif-hash", "")
    expected = current_app.config.get(
        "FLW_WEBHOOK_HASH", ""
    )

    if not expected or not hmac.compare_digest(
        supplied, expected
    ):
        return jsonify(
            error="invalid_webhook_signature"
        ), 401

    payload = request.get_json(silent=True) or {}

    if not isinstance(payload, dict):
        return jsonify(
            error="invalid_refund_webhook_payload"
        ), 400

    data = payload.get("data") or {}

    if not isinstance(data, dict):
        return jsonify(
            error="invalid_refund_webhook_data"
        ), 400

    refund_id = str(
        data.get("id")
        or data.get("refund_id")
        or ""
    )

    status = str(
        data.get("status") or ""
    ).lower()

    if not refund_id or not status:
        return jsonify(
            error="refund_id_and_status_required"
        ), 400

    try:
        from ..models import PaymentRefund, Payment
        from ..extensions import db

        refund = PaymentRefund.query.filter_by(
            provider_refund_id=refund_id
        ).first()

        if not refund:
            return jsonify(
                ok=True,
                ignored=True,
            ), 200

        completed_statuses = {
            "completed-bank-transfer",
            "completed-momo",
            "completed-mpgs",
            "completed-offline",
            "completed-preauth",
            "succeeded",
            "success",
            "successful",
            "refunded",
        }

        if status in completed_statuses:
            refund.status = "COMPLETED"

        elif status in {
            "failed",
            "error",
            "cancelled",
        }:
            refund.status = "FAILED"

        else:
            refund.status = "PROCESSING"

        db.session.commit()

        if refund.status == "COMPLETED":
            from .wallet_service import (
                post_completed_refund,
            )
            from .refund_service import (
                apply_completed_refund_policy,
            )
            from .payment_notifications import (
                notify_payment,
            )

            post_completed_refund(refund)

            payment = Payment.query.get(
                refund.payment_id
            )

            if payment:
                apply_completed_refund_policy(payment)

                notify_payment(
                    payment.user_id,
                    "REFUNDED",
                    payment.tx_ref,
                    payment.plan_code,
                )

        return jsonify(
            ok=True,
            status=refund.status,
        ), 200

    except Exception:
        current_app.logger.exception(
            "Refund webhook processing failed"
        )

        from ..extensions import db

        db.session.rollback()

        return jsonify(
            error="refund_webhook_processing_failed"
        ), 500


@bp.post("/flutterwave/dispute-webhook")
def dispute_webhook():
    supplied = request.headers.get("verif-hash", "")
    expected = current_app.config.get(
        "FLW_WEBHOOK_HASH", ""
    )

    if not expected or not hmac.compare_digest(
        supplied, expected
    ):
        return jsonify(
            error="invalid_webhook_signature"
        ), 401

    payload = request.get_json(silent=True) or {}

    if not isinstance(payload, dict):
        return jsonify(
            error="invalid_dispute_webhook_payload"
        ), 400

    data = payload.get("data") or {}

    if not isinstance(data, dict):
        return jsonify(
            error="invalid_dispute_webhook_data"
        ), 400

    case_id = str(
        data.get("case_id")
        or data.get("id")
        or ""
    )

    transaction_id = str(
        data.get("transaction_id")
        or data.get("flw_id")
        or ""
    )

    tx_ref = str(data.get("tx_ref") or "")

    status = str(
        data.get("status")
        or payload.get("event")
        or "OPEN"
    ).upper()[:24]

    if not case_id or (
        not transaction_id and not tx_ref
    ):
        return jsonify(
            error="dispute_identifiers_required"
        ), 400

    try:
        from ..models import Payment, PaymentDispute
        from ..extensions import db

        payment = None

        if transaction_id:
            payment = Payment.query.filter_by(
                provider_id=transaction_id
            ).first()

        if payment is None and tx_ref:
            payment = Payment.query.filter_by(
                tx_ref=tx_ref
            ).first()

        if payment is None:
            return jsonify(
                ok=True,
                ignored=True,
            ), 200

        dispute = PaymentDispute.query.filter_by(
            provider_case_id=case_id
        ).first()

        details = {
            "reason": str(
                data.get("reason") or ""
            )[:300],
            "amount": str(
                data.get("amount") or ""
            ),
            "currency": str(
                data.get("currency") or ""
            )[:3],
            "event": str(
                payload.get("event") or ""
            )[:80],
        }

        if dispute is None:
            dispute = PaymentDispute(
                payment_id=payment.id,
                provider_case_id=case_id,
                status=status,
                details=details,
            )

        else:
            dispute.status = status
            dispute.details = details

        db.session.add(dispute)
        db.session.commit()

        return jsonify(
            ok=True,
            dispute_id=dispute.id,
            status=dispute.status,
        ), 200

    except Exception:
        current_app.logger.exception(
            "Dispute webhook processing failed"
        )

        from ..extensions import db

        db.session.rollback()

        return jsonify(
            error="dispute_webhook_processing_failed"
        ), 500
