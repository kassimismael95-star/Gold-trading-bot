import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class TestLicenseRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("web.auth.get_current_user")
    @patch("core.license_manager.activate_license")
    def test_activate_license_returns_success(
        self,
        mock_activate_license,
        mock_get_current_user
    ):
        mock_get_current_user.return_value = {
            "id": 1,
            "email": "test@example.com"
        }

        mock_activate_license.return_value = {
            "id": 1,
            "user_id": 1,
            "license_key": "BOSSMODE99",
            "status": "ACTIVE"
        }

        response = self.client.post(
            "/licenses/activate",
            json={
                "license_key": "BOSSMODE99"
            },
            headers={
                "Authorization": "Bearer test-token"
            }
        )

        self.assertEqual(
            response.status_code,
            200
        )

        data = response.json()

        self.assertEqual(
            data["status"],
            "ACTIVE"
        )

        self.assertEqual(
            data["license_key"],
            "BOSSMODE99"
        )

    @patch("web.auth.get_current_user")
    @patch("core.license_manager.activate_license")
    def test_activate_license_rejects_invalid_key(
        self,
        mock_activate_license,
        mock_get_current_user
    ):
        mock_get_current_user.return_value = {
            "id": 1,
            "email": "test@example.com"
        }

        mock_activate_license.side_effect = ValueError(
            "Invalid license key"
        )

        response = self.client.post(
            "/licenses/activate",
            json={
                "license_key": "INVALID-KEY"
            },
            headers={
                "Authorization": "Bearer test-token"
            }
        )

        self.assertEqual(
            response.status_code,
            400
        )

        self.assertEqual(
            response.json()["detail"],
            "Invalid license key"
        )

    @patch("web.auth.get_current_user")
    @patch("core.license_manager.get_license_status")
    def test_get_license_status_returns_active_license(
        self,
        mock_get_license_status,
        mock_get_current_user
    ):
        mock_get_current_user.return_value = {
            "id": 1,
            "email": "test@example.com"
        }

        mock_get_license_status.return_value = {
            "id": 1,
            "user_id": 1,
            "license_key": "BOSSMODE99",
            "status": "ACTIVE"
        }

        response = self.client.get(
            "/licenses/status",
            headers={
                "Authorization": "Bearer test-token"
            }
        )

        self.assertEqual(
            response.status_code,
            200
        )

        data = response.json()

        self.assertEqual(
            data["status"],
            "ACTIVE"
        )

        self.assertEqual(
            data["license_key"],
            "BOSSMODE99"
        )

    @patch("web.auth.get_current_user")
    @patch("core.license_manager.get_license_status")
    def test_get_license_status_returns_none_when_missing(
        self,
        mock_get_license_status,
        mock_get_current_user
    ):
        mock_get_current_user.return_value = {
            "id": 1,
            "email": "test@example.com"
        }

        mock_get_license_status.return_value = None

        response = self.client.get(
            "/licenses/status",
            headers={
                "Authorization": "Bearer test-token"
            }
        )

        self.assertEqual(
            response.status_code,
            404
        )

        self.assertEqual(
            response.json()["detail"],
            "No license found"
        )

    @patch("web.auth.get_current_user")
    @patch("core.license_manager.deactivate_license")
    def test_deactivate_license_returns_success(
        self,
        mock_deactivate_license,
        mock_get_current_user
    ):
        mock_get_current_user.return_value = {
            "id": 1,
            "email": "test@example.com"
        }

        mock_deactivate_license.return_value = True

        response = self.client.post(
            "/licenses/deactivate",
            headers={
                "Authorization": "Bearer test-token"
            }
        )

        self.assertEqual(
            response.status_code,
            200
        )

        self.assertEqual(
            response.json()["status"],
            "DEACTIVATED"
        )

    @patch("web.auth.get_current_user")
    @patch("core.license_manager.deactivate_license")
    def test_deactivate_license_returns_error_when_missing(
        self,
        mock_deactivate_license,
        mock_get_current_user
    ):
        mock_get_current_user.return_value = {
            "id": 1,
            "email": "test@example.com"
        }

        mock_deactivate_license.return_value = False

        response = self.client.post(
            "/licenses/deactivate",
            headers={
                "Authorization": "Bearer test-token"
            }
        )

        self.assertEqual(
            response.status_code,
            404
        )

        self.assertEqual(
            response.json()["detail"],
            "No active license found"
        )


if __name__ == "__main__":
    unittest.main()
