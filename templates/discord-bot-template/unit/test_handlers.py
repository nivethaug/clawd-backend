#!/usr/bin/env python3
"""
Unit tests for API client functions.
Tests the real api_client.py surface: fetch_json, get_crypto_price, safe_get.
"""

import unittest
from unittest.mock import patch, MagicMock

from services.api_client import fetch_json, get_crypto_price, safe_get
from services.mock_data import get_mock_response


class TestAPIClient(unittest.TestCase):
    """Test API client functions."""

    @patch("services.api_client.requests.get")
    def test_get_crypto_price_success(self, mock_get):
        """Test fetching crypto price via get_crypto_price."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"bitcoin": {"usd": 50000.0}}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = get_crypto_price("bitcoin")
        self.assertTrue(result["success"])
        self.assertEqual(result["price"], 50000.0)
        self.assertEqual(result["coin"], "bitcoin")
        mock_get.assert_called_once()

    @patch("services.api_client.requests.get")
    def test_get_crypto_price_unknown_coin(self, mock_get):
        """Unknown coin should return success=False."""
        mock_response = MagicMock()
        mock_response.json.return_value = {}  # Empty — coin not in response
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = get_crypto_price("nonexistentcoin")
        self.assertFalse(result["success"])

    @patch("services.api_client.requests.get")
    def test_get_crypto_price_network_error(self, mock_get):
        """Network error should return success=False, not crash."""
        mock_get.side_effect = Exception("Connection refused")

        result = get_crypto_price("bitcoin")
        self.assertFalse(result["success"])

    @patch("services.api_client.requests.get")
    def test_fetch_json_success(self, mock_get):
        """Test generic GET request."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "ok"}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = fetch_json("https://example.com/api")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["status"], "ok")

    @patch("services.api_client.requests.get")
    def test_fetch_json_timeout(self, mock_get):
        """Timeout should return success=False."""
        import requests
        mock_get.side_effect = requests.exceptions.Timeout()

        result = fetch_json("https://example.com/api")
        self.assertFalse(result["success"])
        self.assertIn("timeout", result["error"].lower())


class TestSafeGet(unittest.TestCase):
    """Test the safe_get nested-dict helper."""

    def test_safe_get_nested(self):
        data = {"a": {"b": {"c": 42}}}
        self.assertEqual(safe_get(data, "a", "b", "c"), 42)

    def test_safe_get_missing_key(self):
        data = {"a": {"b": {}}}
        self.assertIsNone(safe_get(data, "a", "b", "c"))

    def test_safe_get_default(self):
        data = {"a": {}}
        self.assertEqual(safe_get(data, "a", "missing", default="fallback"), "fallback")


class TestMockDataFallback(unittest.TestCase):
    """Test mock data fallback chain."""

    def test_mock_default_includes_user_text(self):
        """Test that default mock includes the user's text."""
        result = get_mock_response("default", text="my question")
        self.assertIn("my question", result)

    def test_mock_default_references_slash_help(self):
        """Default mock should reference /help (not !help)."""
        result = get_mock_response("default", text="test")
        self.assertIn("/help", result)


if __name__ == "__main__":
    unittest.main()
