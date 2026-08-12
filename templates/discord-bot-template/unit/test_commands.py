#!/usr/bin/env python3
"""
Unit tests for AI logic and slash command handlers.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.ai_logic import process_user_input
from services.mock_data import get_mock_response

# Slash handler tests require discord.py (not available in all environments)
try:
    import discord  # noqa: F401
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False


class TestAILogic(unittest.TestCase):
    """Test AI logic processing (the /ask brain)."""

    def test_greeting_hello(self):
        result = process_user_input("hello")
        self.assertIn("Hey", result)

    def test_greeting_hi(self):
        result = process_user_input("hi")
        self.assertIn("Hey", result)

    def test_greeting_hey(self):
        result = process_user_input("hey")
        self.assertIn("Hey", result)

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


@unittest.skipUnless(DISCORD_AVAILABLE, "discord.py not installed — slash handler tests run in Docker")
class TestSlashHandlers(unittest.TestCase):
    """Smoke tests for slash command handlers (interaction-based)."""

    def _make_interaction(self):
        """Create a mock Interaction with an async send_message."""
        interaction = MagicMock()
        interaction.user = MagicMock()
        interaction.user.__str__ = lambda self: "TestUser#1234"
        interaction.user.mention = "@TestUser"
        interaction.response.send_message = AsyncMock()
        return interaction

    @patch("commands.ask.process_user_input")
    def test_ask_handler_responds(self, mock_process):
        """ask_handler should call process_user_input and send the result."""
        from commands.ask import ask_handler
        mock_process.return_value = "Bitcoin Price: $50,000.00"
        interaction = self._make_interaction()

        import asyncio
        asyncio.run(ask_handler(interaction, "btc price"))

        mock_process.assert_called_once_with("btc price")
        interaction.response.send_message.assert_awaited_once_with("Bitcoin Price: $50,000.00")

    def test_help_handler_responds(self):
        """help_handler should send help text with / commands."""
        from commands.help import help_handler
        interaction = self._make_interaction()

        import asyncio
        asyncio.run(help_handler(interaction))

        interaction.response.send_message.assert_awaited_once()
        sent_text = interaction.response.send_message.call_args[0][0]
        self.assertIn("/ask", sent_text)
        self.assertIn("/start", sent_text)

    def test_status_handler_responds(self):
        """status_handler should send bot status."""
        from commands.status import status_handler
        interaction = self._make_interaction()
        interaction.client.guilds = [1, 2, 3]
        interaction.client.latency = 0.05

        import asyncio
        asyncio.run(status_handler(interaction))

        interaction.response.send_message.assert_awaited_once()
        sent_text = interaction.response.send_message.call_args[0][0]
        self.assertIn("Guilds: 3", sent_text)


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

    def test_default_mock_references_slash_help(self):
        """Default mock should reference /help (not !help)."""
        result = get_mock_response("default", text="test")
        self.assertIn("/help", result)


if __name__ == "__main__":
    unittest.main()
