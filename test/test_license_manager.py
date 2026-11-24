import os
import unittest
from unittest.mock import patch

from core.license_manager import (
    get_allowed_licenses,
    is_recognized_license,
    normalize_license_key,
    validate_license,
    LicenseConfigurationError
)


class TestLicenseManager(unittest.TestCase):
    def test_all_supported_licenses_are_recognized_by_default(self):
        with patch.dict(
            os.environ,
            {},
            clear=False
        ):
            os.environ.pop("ALLOWED_LICENSES", None)

            allowed = get_allowed_licenses()

            self.assertIn("BOSSMODE99", allowed)
            self.assertIn("BOSSMODE98", allowed)
            self.assertIn("BOSSMODE30D", allowed)
            self.assertIn("BOSSMODE01D", allowed)

    def test_license_key_is_normalized(self):
        self.assertEqual(
            normalize_license_key("  BOSSMODE99  "),
            "BOSSMODE99"
        )

    def test_recognized_license_returns_true(self):
        with patch.dict(
            os.environ,
            {
                "ALLOWED_LICENSES": "BOSSMODE99,BOSSMODE98"
            }
        ):
            self.assertTrue(
                is_recognized_license("BOSSMODE99")
            )

    def test_unrecognized_license_returns_false(self):
        with patch.dict(
            os.environ,
            {
                "ALLOWED_LICENSES": "BOSSMODE99,BOSSMODE98"
            }
        ):
            self.assertFalse(
                is_recognized_license("BOSSMODE01D")
            )

    def test_empty_license_key_returns_false(self):
        self.assertFalse(
            is_recognized_license("")
        )

    def test_validate_license_recognizes_supported_key(self):
        with patch.dict(
            os.environ,
            {
                "ALLOWED_LICENSES": "BOSSMODE99,BOSSMODE98,BOSSMODE30D,BOSSMODE01D"
            }
        ):
            result = validate_license("BOSSMODE30D")

            self.assertTrue(result["recognized"])
            self.assertFalse(result["authorized"])
            self.assertEqual(
                result["reason"],
                "SERVER_SIDE_ENTITLEMENT_CHECK_REQUIRED"
            )

    def test_validate_license_rejects_unknown_key(self):
        result = validate_license("INVALID_KEY")

        self.assertFalse(result["recognized"])
        self.assertFalse(result["authorized"])
        self.assertEqual(
            result["reason"],
            "LICENSE_KEY_NOT_ALLOWED"
        )

    def test_empty_configuration_disables_all_keys(self):
        with patch.dict(
            os.environ,
            {
                "ALLOWED_LICENSES": ""
            }
        ):
            self.assertFalse(
                is_recognized_license("BOSSMODE99")
            )

    def test_unsupported_configuration_raises_error(self):
        with patch.dict(
            os.environ,
            {
                "ALLOWED_LICENSES": "BOSSMODE99,FAKE_KEY"
            }
        ):
            with self.assertRaises(
                LicenseConfigurationError
            ):
                get_allowed_licenses()


if __name__ == "__main__":
    unittest.main()
