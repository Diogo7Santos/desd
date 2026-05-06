import json
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from accounts.postcodes import (
    POSTCODE_NOT_FOUND_ERROR_MESSAGE,
    clean_uk_postcode,
    lookup_postcode,
)


class PostcodesIoIntegrationTests(SimpleTestCase):
    @override_settings(POSTCODES_IO_ENABLED=True)
    @patch("accounts.postcodes.urlopen")
    def test_lookup_postcode_returns_live_coordinates(self, mocked_urlopen):
        mocked_response = Mock()
        mocked_response.read.return_value = json.dumps(
            {
                "status": 200,
                "result": {
                    "postcode": "BS7 0SJ",
                    "latitude": 51.487,
                    "longitude": -2.58,
                    "outcode": "BS7",
                    "country": "England",
                    "region": "South West",
                },
            }
        ).encode("utf-8")
        mocked_urlopen.return_value.__enter__.return_value = mocked_response

        result = lookup_postcode("bs70sj")

        self.assertEqual(result["postcode"], "BS7 0SJ")
        self.assertEqual(result["latitude"], 51.487)
        self.assertEqual(result["longitude"], -2.58)
        self.assertEqual(result["outcode"], "BS7")

    @override_settings(POSTCODES_IO_ENABLED=True)
    @patch("accounts.postcodes.urlopen")
    def test_clean_uk_postcode_rejects_format_valid_but_unknown_postcode(self, mocked_urlopen):
        mocked_urlopen.side_effect = HTTPError(
            url="https://api.postcodes.io/postcodes/ZZ1%201ZZ",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )

        with self.assertRaises(ValidationError) as exc:
            clean_uk_postcode("ZZ1 1ZZ")

        self.assertIn(POSTCODE_NOT_FOUND_ERROR_MESSAGE, exc.exception.messages)
