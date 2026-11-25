"""Authenticated encryption for stored broker secrets using AES-GCM."""
import os,base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

def _key():
 raw=os.environ.get("CREDENTIAL_ENCRYPTION_KEY","")
 try:key=base64.urlsafe_b64decode(raw+'='*((4-len(raw)%4)%4))
 except Exception as exc:raise RuntimeError("invalid_encryption_key") from exc
 if len(key)!=32:raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY_must_be_base64_32_bytes")
 return key

def encrypt_secret(value,associated_data=None):
 nonce=os.urandom(12)
 aad=associated_data.encode() if isinstance(associated_data,str) else associated_data
 cipher=AESGCM(_key()).encrypt(nonce,str(value).encode(),aad)
 return base64.urlsafe_b64encode(nonce+cipher).decode()

def decrypt_secret(value,associated_data=None):
 raw=base64.urlsafe_b64decode(value)
 aad=associated_data.encode() if isinstance(associated_data,str) else associated_data
 return AESGCM(_key()).decrypt(raw[:12],raw[12:],aad).decode()
