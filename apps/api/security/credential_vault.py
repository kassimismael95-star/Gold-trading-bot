"""Credential vault primitives. Persist ciphertext only; never log plaintext."""
from .encryption import encrypt_secret,decrypt_secret

def seal_mt5_password(password,account_id=None):
 if not password or len(password)>512:raise ValueError("invalid_password")
 aad=f"mt5-account:{account_id}" if account_id is not None else None
 return encrypt_secret(password,aad)

def open_mt5_password(ciphertext,account_id=None):
 aad=f"mt5-account:{account_id}" if account_id is not None else None
 return decrypt_secret(ciphertext,aad)
