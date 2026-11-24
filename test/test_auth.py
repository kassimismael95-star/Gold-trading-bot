import os
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone

from web.auth import (
    create_session,
    get_session,
    require_authenticated_user,
    sign_out
)


class TestAuth(unittest.TestCase):
    def setUp(self):
        self.mock_connection = MagicMock()
        self.mock_cursor = MagicMock()

        self.mock_connection.cursor.return_value = (
            self.mock_cursor
        )

    @patch("web.auth.get_connection")
    def test_create_session_returns_token(self, mock_get_connection):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.fetchone.return_value = {
            "id": 1
        }

        session = create_session(user_id=1)

        self.assertIsNotNone(session["session_token"])
        self.assertEqual(session["session_id"], 1)
        self.assertGreater(
            session["expires_at"],
            datetime.now(timezone.utc)
        )

    @patch("web.auth.get_connection")
    def test_get_session_returns_none_without_token(
        self,
        mock_get_connection
    ):
        session = get_session(None)

        self.assertIsNone(session)

    @patch("web.auth.get_connection")
    def test_get_session_returns_session(self, mock_get_connection):
        mock_get_connection.return_value = self.mock_connection

        expires_at = datetime.now(timezone.utc) + timedelta(days=1)

        self.mock_cursor.fetchone.return_value = {
            "session_id": 1,
            "user_id": 1,
            "expires_at": expires_at,
            "email": "test@example.com"
        }

        session = get_session("valid-token")

        self.assertEqual(session["user_id"], 1)
        self.assertEqual(
            session["email"],
            "test@example.com"
        )

    @patch("web.auth.get_connection")
    def test_require_authenticated_user_returns_session(
        self,
        mock_get_connection
    ):
        mock_get_connection.return_value = self.mock_connection

        expires_at = datetime.now(timezone.utc) + timedelta(days=1)

        self.mock_cursor.fetchone.return_value = {
            "session_id": 1,
            "user_id": 1,
            "expires_at": expires_at,
            "email": "test@example.com"
        }

        request = MagicMock()
        request.cookies = {
            "session_token": "valid-token"
        }

        session = require_authenticated_user(request)

        self.assertEqual(session["user_id"], 1)

    @patch("web.auth.get_connection")
    def test_require_authenticated_user_rejects_missing_token(
        self,
        mock_get_connection
    ):
        request = MagicMock()
        request.cookies = {}

        with self.assertRaises(PermissionError):
            require_authenticated_user(request)

    @patch("web.auth.get_connection")
    def test_sign_out_deletes_session(self, mock_get_connection):
        mock_get_connection.return_value = self.mock_connection

        self.mock_cursor.rowcount = 1

        deleted = sign_out("valid-token")

        self.assertTrue(deleted)

    @patch("web.auth.get_connection")
    def test_sign_out_returns_false_without_token(
        self,
        mock_get_connection
    ):
        deleted = sign_out(None)

        self.assertFalse(deleted)


if __name__ == "__main__":
    unittest.main()
