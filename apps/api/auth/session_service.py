"""JWT session lifecycle with access/refresh tokens and per-user revocation."""
from flask_jwt_extended import create_access_token,create_refresh_token
ACCESS_TOKEN_MINUTES=30
REFRESH_TOKEN_DAYS=14
def token_identity(user):return str(user.id)
def create_user_tokens(user):
    claims={"session_version":int(user.session_version or 0)}
    return {"access_token":create_access_token(identity=token_identity(user),additional_claims=claims),
            "refresh_token":create_refresh_token(identity=token_identity(user),additional_claims=claims)}
