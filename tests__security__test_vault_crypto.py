import os,base64
from apps.api.security.encryption import encrypt_secret,decrypt_secret

def test_authenticated_encryption_roundtrip(monkeypatch):
 monkeypatch.setenv('CREDENTIAL_ENCRYPTION_KEY',base64.urlsafe_b64encode(os.urandom(32)).decode())
 cipher=encrypt_secret('secret-demo')
 assert cipher!='secret-demo' and decrypt_secret(cipher)=='secret-demo'

def test_account_bound_ciphertext_cannot_be_swapped(monkeypatch):
 import pytest
 from cryptography.exceptions import InvalidTag
 monkeypatch.setenv('CREDENTIAL_ENCRYPTION_KEY',base64.urlsafe_b64encode(os.urandom(32)).decode())
 cipher=encrypt_secret('broker-password','mt5-account:101')
 assert decrypt_secret(cipher,'mt5-account:101')=='broker-password'
 with pytest.raises(InvalidTag):
  decrypt_secret(cipher,'mt5-account:202')
