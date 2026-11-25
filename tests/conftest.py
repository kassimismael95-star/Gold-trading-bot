import os, base64, secrets
import pytest

@pytest.fixture(autouse=True)
def test_credential_key(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
