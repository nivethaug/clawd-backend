#!/usr/bin/env python3
"""
Unit tests for message handlers and API client.
"""

import unittest
from unittest.mock import patch, MagicMock

from services.api_client import fetch_data, get_json, post_json, API_URLS
from services.mock_data import get_mock_response


class TestAPIClient(unittest.TestCase):
    """Test API client functions."""

    @patch("services.api_client.requests.get")
    def test_fetch_bitcoin_success(self, mock_get):
        """Test fetching Bitcoin price."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"bitcoin": {"usd": 50000.0}}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        data = fetch_data("bitcoin")
        self.assertEqual(data["bitcoin"]["usd"], 50000.0)
        mock_get.assert_called_once()

    def test_fetch_unknown_api_raises(self):
        """Test that unknown API name raises ValueError."""
        with self.assertRaises(ValueError):
            fetch_data("unknown_api")

    @patch("services.api_client.requests.get")
    def test_get_json_success(self, mock_get):
        """Test generic GET request."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "ok"}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = get_json("https://example.com/api")
        self.assertEqual(result["status"], "ok")

    @patch("services.api_client.requests.post")
    def test_post_json_success(self, mock_post):
        """Test generic POST request."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"created": True}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = post_json("https://example.com/api", data={"key": "value"})
        self.assertTrue(result["created"])

    def test_api_urls_has_bitcoin(self):
        """Test that Bitcoin API URL is configured."""
        self.assertIn("bitcoin", API_URLS)


class TestMockDataFallback(unittest.TestCase):
    """Test mock data fallback chain."""

    def test_mock_responses_have_required_keys(self):
        """Test all required mock categories exist."""
        required_keys = ["bitcoin", "ethereum", "default"]
        for key in required_keys:
            self.assertIn(key, get_mock_response.__module__ and "mock_data", f"Missing mock key: {key}")

    def test_mock_default_includes_user_text(self):
        """Test that default mock includes the user's text."""
        result = get_mock_response("default", text="my question")
        self.assertIn("my question", result)


if __name__ == "__main__":
    unittest.main()
