import os
import base64
from cryptography.fernet import Fernet


def get_encryption_key():
    secret_key = os.environ.get("SECRET_KEY")

    if not secret_key:
        raise ValueError("SECRET_KEY is missing.")

    key_material = secret_key.encode("utf-8")

    key = base64.urlsafe_b64encode(
        key_material.ljust(32, b"0")[:32]
    )

    return key


def encrypt_password(password):
    fernet = Fernet(get_encryption_key())

    encrypted_password = fernet.encrypt(
        password.encode("utf-8")
    )

    return encrypted_password.decode("utf-8")


def decrypt_password(encrypted_password):
    fernet = Fernet(get_encryption_key())

    decrypted_password = fernet.decrypt(
        encrypted_password.encode("utf-8")
    )

    return decrypted_password.decode("utf-8")
