import os
import unittest
from unittest.mock import patch

from accounts.credential_vault import (
    encrypt_password,
    decrypt_password
)


class TestCredentialVault(unittest.TestCase):
    def test_encrypt_password_returns_different_value(self):
        with patch.dict(
            os.environ,
            {
                "SECRET_KEY": "test-secret-key-for-unit-tests"
            }
        ):
            encrypted = encrypt_password("test-password")

            self.assertNotEqual(
                encrypted,
                "test-password"
            )

    def test_decrypt_password_returns_original_value(self):
        with patch.dict(
            os.environ,
            {
                "SECRET_KEY": "test-secret-key-for-unit-tests"
            }
        ):
            encrypted = encrypt_password("test-password")

            decrypted = decrypt_password(encrypted)

            self.assertEqual(
                decrypted,
                "test-password"
            )

    def test_encrypt_password_rejects_empty_password(self):
        with patch.dict(
            os.environ,
            {
                "SECRET_KEY": "test-secret-key-for-unit-tests"
            }
        ):
            with self.assertRaises(ValueError):
                encrypt_password("")

    def test_decrypt_password_rejects_empty_value(self):
        with patch.dict(
            os.environ,
            {
                "SECRET_KEY": "test-secret-key-for-unit-tests"
            }
        ):
            with self.assertRaises(ValueError):
                decrypt_password("")

    def test_missing_secret_key_raises_error(self):
        with patch.dict(
            os.environ,
            {},
            clear=False
        ):
            os.environ.pop("SECRET_KEY", None)

            with self.assertRaises(RuntimeError):
                encrypt_password("test-password")

    def test_wrong_secret_key_cannot_decrypt_password(self):
        with patch.dict(
            os.environ,
            {
                "SECRET_KEY": "first-test-secret-key"
            }
        ):
            encrypted = encrypt_password("test-password")

        with patch.dict(
            os.environ,
            {
                "SECRET_KEY": "second-test-secret-key"
            }
        ):
            with self.assertRaises(Exception):
                decrypt_password(encrypted)


if __name__ == "__main__":
    unittest.main()
