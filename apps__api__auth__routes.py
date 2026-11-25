from datetime import datetime, timezone, timedelta
import secrets
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity, decode_token
from ..extensions import db
from ..models import User, EmailChallenge
from .otp_service import generate_otp, hash_otp, verify_otp
from .email_service import send_email
from .rate_limiter import RateLimiter

bp = Blueprint("auth", __name__, url_prefix="/api/auth")
_limiter = RateLimiter(limit=8, window=300)
OTP_TTL = timedelta(minutes=10)
RESET_TTL = timedelta(minutes=30)
MAX_ATTEMPTS = 5

def _issue(user, purpose):
    now = datetime.now(timezone.utc)
    # invalidate older active challenges for this purpose
    EmailChallenge.query.filter_by(user_id=user.id, purpose=purpose, consumed_at=None).update({"consumed_at": now})
    code = generate_otp(); salt = secrets.token_hex(16)
    row = EmailChallenge(user_id=user.id, purpose=purpose, salt=salt,
        code_hash=hash_otp(code, salt), expires_at=now + (OTP_TTL if purpose == "VERIFY" else RESET_TTL))
    db.session.add(row); db.session.commit()
    return code

def _send(user, purpose, code):
    if purpose == "VERIFY":
        subject = "Verify your Gold Trading Bot account"
        body = f"Your email verification code is {code}. It expires in 10 minutes."
    else:
        subject = "Gold Trading Bot password reset"
        body = f"Your password reset code is {code}. It expires in 30 minutes. If you did not request this, ignore this email."
    send_email(user.email, subject, body)

@bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower(); password = str(data.get("password", ""))
    key = "register:" + (request.remote_addr or "unknown")
    if not _limiter.allow(key): return jsonify(error="rate_limited"), 429
    if "@" not in email or len(email)>254 or len(password) < 12 or len(password)>512:
        return jsonify(error="valid_email_and_password_min_12_chars_required"), 400
    if User.query.filter_by(email=email).first(): return jsonify(error="email_already_registered"), 409
    user = User(email=email); user.set_password(password); user.email_verified = False
    db.session.add(user); db.session.commit()
    # Local/test convenience preserves the original starter workflow. Production
    # must configure SMTP and complete the OTP challenge before login.
    smtp_configured = bool(__import__("os").getenv("SMTP_HOST") and __import__("os").getenv("EMAIL_FROM"))
    if current_app.config.get("APP_ENV") != "production" and not smtp_configured:
        user.email_verified = True; db.session.commit()
        from .session_service import create_user_tokens
        return jsonify(**create_user_tokens(user),user={"id":user.id,"email":user.email}),201
    code = _issue(user, "VERIFY")
    try: _send(user, "VERIFY", code)
    except Exception:
        current_app.logger.warning("verification email delivery unavailable for user_id=%s", user.id)
        return jsonify(error="verification_email_delivery_failed", user_id=user.id), 503
    return jsonify(message="verification_code_sent"), 201

@bp.post("/verify-email")
def verify_email():
    data=request.get_json(silent=True) or {}; email=str(data.get("email", "")).strip().lower(); code=str(data.get("code", ""))
    if not _limiter.allow("verify:"+(request.remote_addr or "unknown")+":"+email): return jsonify(error="rate_limited"),429
    user=User.query.filter_by(email=email).first()
    if not user: return jsonify(error="invalid_or_expired_code"), 400
    row=EmailChallenge.query.filter_by(user_id=user.id,purpose="VERIFY",consumed_at=None).order_by(EmailChallenge.id.desc()).first()
    if not row: return jsonify(error="invalid_or_expired_code"), 400
    now=datetime.now(timezone.utc); exp=row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if now>=exp or row.attempts>=MAX_ATTEMPTS: return jsonify(error="invalid_or_expired_code"), 400
    row.attempts += 1
    if not verify_otp(code,row.salt,row.code_hash): db.session.commit(); return jsonify(error="invalid_or_expired_code"), 400
    row.consumed_at=now; user.email_verified=True; db.session.commit()
    from .session_service import create_user_tokens
    return jsonify(**create_user_tokens(user),user={"id":user.id,"email":user.email}),200

@bp.post("/verification/resend")
def resend_verification():
    data=request.get_json(silent=True) or {}; email=str(data.get("email", "")).strip().lower()
    if not _limiter.allow("resend:"+(request.remote_addr or "unknown")+":"+email): return jsonify(error="rate_limited"),429
    user=User.query.filter_by(email=email).first()
    if not user or user.email_verified: return jsonify(message="if_account_requires_verification_code_was_sent"),200
    recent=EmailChallenge.query.filter_by(user_id=user.id,purpose="VERIFY").order_by(EmailChallenge.id.desc()).first()
    if recent:
        created=recent.created_at if recent.created_at.tzinfo else recent.created_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc)-created < timedelta(seconds=60): return jsonify(error="resend_cooldown"),429
    code=_issue(user,"VERIFY")
    try: _send(user,"VERIFY",code)
    except Exception: return jsonify(error="verification_email_delivery_failed"),503
    return jsonify(message="verification_code_sent"),200

@bp.post("/login")
def login():
    data=request.get_json(silent=True) or {}; email=str(data.get("email", "")).strip().lower()
    if not _limiter.allow("login:"+(request.remote_addr or "unknown")+":"+email): return jsonify(error="rate_limited"),429
    user=User.query.filter_by(email=email).first()
    if not user or len(str(data.get("password", "")))>512 or not user.check_password(str(data.get("password", ""))): return jsonify(error="invalid_credentials"),401
    if not user.email_verified and user.role != "admin": return jsonify(error="email_verification_required"),403
    from .session_service import create_user_tokens
    return jsonify(**create_user_tokens(user),user={"id":user.id,"email":user.email})

@bp.post("/password-reset/request")
def password_reset_request():
    data=request.get_json(silent=True) or {}; email=str(data.get("email", "")).strip().lower()
    if not _limiter.allow("reset:"+(request.remote_addr or "unknown")): return jsonify(error="rate_limited"),429
    user=User.query.filter_by(email=email).first()
    # Avoid account enumeration: always return the same response.
    if user:
        code=_issue(user,"RESET")
        try: _send(user,"RESET",code)
        except Exception: current_app.logger.warning("password reset delivery unavailable for user_id=%s",user.id)
    return jsonify(message="if_account_exists_reset_code_was_sent"),200

@bp.post("/password-reset/confirm")
def password_reset_confirm():
    data=request.get_json(silent=True) or {}; email=str(data.get("email", "")).strip().lower()
    if not _limiter.allow("reset-confirm:"+(request.remote_addr or "unknown")+":"+email): return jsonify(error="rate_limited"),429
    code=str(data.get("code", "")); password=str(data.get("new_password", ""))
    if len(password)<12 or len(password)>512: return jsonify(error="password_length_must_be_12_to_512_chars"),400
    user=User.query.filter_by(email=email).first()
    row=EmailChallenge.query.filter_by(user_id=user.id,purpose="RESET",consumed_at=None).order_by(EmailChallenge.id.desc()).first() if user else None
    if not row: return jsonify(error="invalid_or_expired_code"),400
    now=datetime.now(timezone.utc); exp=row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if now>=exp or row.attempts>=MAX_ATTEMPTS: return jsonify(error="invalid_or_expired_code"),400
    row.attempts+=1
    if not verify_otp(code,row.salt,row.code_hash): db.session.commit(); return jsonify(error="invalid_or_expired_code"),400
    row.consumed_at=now; user.set_password(password); user.session_version=(user.session_version or 0)+1; db.session.commit()
    return jsonify(message="password_reset_successful"),200


@bp.post("/refresh")
@jwt_required(refresh=True)
def refresh_access_token():
    identity=str(get_jwt_identity())
    user=User.query.get(int(identity))
    if not user:return jsonify(error="user_not_found"),401
    from .session_service import create_user_tokens
    return jsonify(access_token=create_user_tokens(user)["access_token"]),200

@bp.post("/logout")
@jwt_required()
def logout():
    claims=get_jwt(); user_id=int(get_jwt_identity())
    from ..models import TokenBlocklist
    from ..extensions import db
    from datetime import datetime,timezone
    access=TokenBlocklist(jti=claims["jti"],user_id=user_id,
        expires_at=datetime.fromtimestamp(claims["exp"],timezone.utc))
    db.session.merge(access)
    data=request.get_json(silent=True) or {}; refresh=str(data.get("refresh_token", ""))
    if refresh:
        try:
            refresh_claims=decode_token(refresh)
            if refresh_claims.get("sub")==str(user_id) and refresh_claims.get("type")=="refresh":
                db.session.merge(TokenBlocklist(jti=refresh_claims["jti"],user_id=user_id,
                    expires_at=datetime.fromtimestamp(refresh_claims["exp"],timezone.utc)))
        except Exception:
            # The access token is still revoked; an invalid/expired refresh token
            # cannot be used to obtain a new access token.
            pass
    db.session.commit()
    return jsonify(ok=True),200

@bp.post("/logout-refresh")
@jwt_required(refresh=True)
def logout_refresh():
    claims=get_jwt(); user_id=int(get_jwt_identity())
    from ..models import TokenBlocklist
    from ..extensions import db
    from datetime import datetime,timezone
    db.session.merge(TokenBlocklist(jti=claims["jti"],user_id=user_id,
        expires_at=datetime.fromtimestamp(claims["exp"],timezone.utc)))
    db.session.commit()
    return jsonify(ok=True),200
