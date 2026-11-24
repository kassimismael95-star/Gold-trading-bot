import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from web.auth import (
    hash_password,
    verify_password,
    create_access_token,
    verify_token
)

from main import app


class TestSecurity(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_hash_password_does_not_return_plain_text(self):
        hashed = hash_password("TestPassword123")

        self.assertNotEqual(
            hashed,
            "TestPassword123"
        )

    def test_verify_password_accepts_correct_password(self):
        hashed = hash_password("TestPassword123")

        result = verify_password(
            plain_password="TestPassword123",
            hashed_password=hashed
        )

        self.assertTrue(result)

    def test_verify_password_rejects_wrong_password(self):
        hashed = hash_password("TestPassword123")

        result = verify_password(
            plain_password="WrongPassword123",
            hashed_password=hashed
        )

        self.assertFalse(result)

    @patch.dict(
        os.environ,
        {
            "SECRET_KEY": "test-secret-key-for-unit-tests"
        }
    )
    def test_create_access_token_returns_token(self):
        token = create_access_token(
            user_id=1,
            email="test@example.com"
        )

        self.assertIsInstance(token, str)
        self.assertNotEqual(token, "")

    @patch.dict(
        os.environ,
        {
            "SECRET_KEY": "test-secret-key-for-unit-tests"
        }
    )
    def test_verify_token_returns_payload(self):
        token = create_access_token(
            user_id=1,
            email="test@example.com"
        )

        payload = verify_token(token)

        self.assertEqual(
            payload["user_id"],
            1
        )

        self.assertEqual(
            payload["email"],
            "test@example.com"
        )

    @patch.dict(
        os.environ,
        {
            "SECRET_KEY": "test-secret-key-for-unit-tests"
        }
    )
    def test_verify_token_rejects_invalid_token(self):
        with self.assertRaises(Exception):
            verify_token("invalid-token")

    @patch.dict(
        os.environ,
        {
            "WORKER_SHARED_SECRET": "test-worker-secret"
        }
    )
    def test_worker_endpoint_rejects_missing_secret(self):
        response = self.client.get(
            "/worker/commands/next"
        )

        self.assertEqual(
            response.status_code,
            401
        )

    @patch.dict(
        os.environ,
        {
            "WORKER_SHARED_SECRET": "test-worker-secret"
        }
    )
    def test_worker_endpoint_rejects_wrong_secret(self):
        response = self.client.get(
            "/worker/commands/next",
            headers={
                "X-Worker-Secret": "wrong-secret"
            }
        )

        self.assertEqual(
            response.status_code,
            401
        )

    def test_protected_route_rejects_missing_token(self):
        response = self.client.get(
            "/accounts"
        )

        self.assertEqual(
            response.status_code,
            401
        )

    def test_protected_route_rejects_invalid_token(self):
        response = self.client.get(
            "/accounts",
            headers={
                "Authorization": "Bearer invalid-token"
            }
        )

        self.assertEqual(
            response.status_code,
            401
        )


if __name__ == "__main__":
    unittest.main()
