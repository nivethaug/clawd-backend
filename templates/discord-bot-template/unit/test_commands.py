#!/usr/bin/env python3
"""
Unit tests for command handlers.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.ai_logic import process_user_input
from services.mock_data import get_mock_response


class TestAILogic(unittest.TestCase):
    """Test AI logic processing."""

    def test_greeting_hello(self):
        result = process_user_input("hello")
        self.assertIn("Hey", result)

    def test_greeting_hi(self):
        result = process_user_input("hi")
        self.assertIn("Hey", result)

    def test_greeting_hey(self):
        result = process_user_input("hey")
        self.assertIn("Hey", result)

    def test_whoami(self):
        result = process_user_input("whoami")
        self.assertIn("!start", result)

    def test_help_intent(self):
        result = process_user_input("help me")
        self.assertIn("!help", result)

    def test_bitcoin_intent(self):
        """Bitcoin query should try API, fallback to mock."""
        result = process_user_input("btc price")
        # Either real price or mock response
        self.assertTrue("Bitcoin" in result or "mock" in result)

    def test_default_fallback(self):
        result = process_user_input("random text xyz")
        self.assertIn("random text xyz", result)

    def test_case_insensitive(self):
        result = process_user_input("HELLO")
        self.assertIn("Hey", result)

    def test_whitespace_handling(self):
        result = process_user_input("  hello  ")
        self.assertIn("Hey", result)


class TestMockData(unittest.TestCase):
    """Test mock data responses."""

    def test_bitcoin_mock(self):
        result = get_mock_response("bitcoin")
        self.assertIn("Bitcoin", result)

    def test_default_mock_with_text(self):
        result = get_mock_response("default", text="test message")
        self.assertIn("test message", result)

    def test_unknown_category_falls_to_default(self):
        result = get_mock_response("nonexistent", text="hello")
        self.assertIn("hello", result)

    def test_ethereum_mock(self):
        result = get_mock_response("ethereum")
        self.assertIn("Ethereum", result)


if __name__ == "__main__":
    unittest.main()
