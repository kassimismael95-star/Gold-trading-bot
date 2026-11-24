import base64
import os

from cryptography.fernet import Fernet, InvalidToken


class CredentialVault:
    def __init__(self, secret_key: str | None = None):
        self.secret_key = secret_key or os.getenv("SECRET_KEY", "")

        if not self.secret_key:
            raise RuntimeError("SECRET_KEY is required for credential encryption.")

        self._fernet = Fernet(self._derive_key(self.secret_key))

    @staticmethod
    def _derive_key(secret_key: str) -> bytes:
        digest = __import__("hashlib").sha256(secret_key.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            raise ValueError("Credential value cannot be empty.")

        encrypted = self._fernet.encrypt(plaintext.encode("utf-8"))
        return encrypted.decode("utf-8")

    def decrypt(self, encrypted_value: str) -> str:
        if not encrypted_value:
            raise ValueError("Encrypted credential value cannot be empty.")

        try:
            decrypted = self._fernet.decrypt(encrypted_value.encode("utf-8"))
            return decrypted.decode("utf-8")
        except InvalidToken as error:
            raise ValueError("Invalid encrypted credential or wrong SECRET_KEY.") from error

    def mask(self, value: str) -> str:
        if not value:
            return ""

        if len(value) <= 4:
            return "****"

        return f"****{value[-4:]}"
