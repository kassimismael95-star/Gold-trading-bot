import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class TestAuth(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("web.auth.create_user")
    @patch("web.auth.hash_password")
    def test_register_user_returns_success(
        self,
        mock_hash_password,
        mock_create_user
    ):
        mock_hash_password.return_value = "hashed-password"

        mock_create_user.return_value = {
            "id": 1,
            "email": "test@example.com"
        }

        response = self.client.post(
            "/auth/register",
            json={
                "email": "test@example.com",
                "password": "TestPassword123"
            }
        )

        self.assertEqual(
            response.status_code,
            200
        )

        data = response.json()

        self.assertEqual(
            data["email"],
            "test@example.com"
        )

        self.assertEqual(
            data["id"],
            1
        )

    @patch("web.auth.create_user")
    @patch("web.auth.hash_password")
    def test_register_user_rejects_duplicate_email(
        self,
        mock_hash_password,
        mock_create_user
    ):
        mock_hash_password.return_value = "hashed-password"

        mock_create_user.side_effect = ValueError(
            "Email already registered"
        )

        response = self.client.post(
            "/auth/register",
            json={
                "email": "test@example.com",
                "password": "TestPassword123"
            }
        )

        self.assertEqual(
            response.status_code,
            400
        )

        self.assertEqual(
            response.json()["detail"],
            "Email already registered"
        )

    @patch("web.auth.verify_password")
    @patch("web.auth.get_user_by_email")
    @patch("web.auth.create_access_token")
    def test_login_returns_access_token(
        self,
        mock_create_access_token,
        mock_get_user_by_email,
        mock_verify_password
    ):
        mock_get_user_by_email.return_value = {
            "id": 1,
            "email": "test@example.com",
            "password_hash": "hashed-password"
        }

        mock_verify_password.return_value = True

        mock_create_access_token.return_value = "test-access-token"

        response = self.client.post(
            "/auth/login",
            json={
                "email": "test@example.com",
                "password": "TestPassword123"
            }
        )

        self.assertEqual(
            response.status_code,
            200
        )

        data = response.json()

        self.assertEqual(
            data["access_token"],
            "test-access-token"
        )

        self.assertEqual(
            data["token_type"],
            "bearer"
        )

    @patch("web.auth.verify_password")
    @patch("web.auth.get_user_by_email")
    def test_login_rejects_invalid_password(
        self,
        mock_get_user_by_email,
        mock_verify_password
    ):
        mock_get_user_by_email.return_value = {
            "id": 1,
            "email": "test@example.com",
            "password_hash": "hashed-password"
        }

        mock_verify_password.return_value = False

        response = self.client.post(
            "/auth/login",
            json={
                "email": "test@example.com",
                "password": "WrongPassword123"
            }
        )

        self.assertEqual(
            response.status_code,
            401
        )

        self.assertEqual(
            response.json()["detail"],
            "Invalid email or password"
        )

    @patch("web.auth.get_user_by_email")
    def test_login_rejects_unknown_email(
        self,
        mock_get_user_by_email
    ):
        mock_get_user_by_email.return_value = None

        response = self.client.post(
            "/auth/login",
            json={
                "email": "unknown@example.com",
                "password": "TestPassword123"
            }
        )

        self.assertEqual(
            response.status_code,
            401
        )

        self.assertEqual(
            response.json()["detail"],
            "Invalid email or password"
        )

    @patch("web.auth.get_current_user")
    def test_protected_route_accepts_valid_token(
        self,
        mock_get_current_user
    ):
        mock_get_current_user.return_value = {
            "id": 1,
            "email": "test@example.com"
        }

        response = self.client.get(
            "/auth/me",
            headers={
                "Authorization": "Bearer test-access-token"
            }
        )

        self.assertEqual(
            response.status_code,
            200
        )

        self.assertEqual(
            response.json()["email"],
            "test@example.com"
        )

    def test_protected_route_rejects_missing_token(self):
        response = self.client.get(
            "/auth/me"
        )

        self.assertEqual(
            response.status_code,
            401
        )

    def test_protected_route_rejects_invalid_token(self):
        response = self.client.get(
            "/auth/me",
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
