"""
Unit tests for Telegram bot command handlers.

Tests command registration, execution, and responses.
Run with: python -m pytest unit/test_commands.py -v

NOTE: python-telegram-bot v20 freezes Update objects — you CANNOT set
attributes directly (update.message = ... raises AttributeError).
Use MagicMock with __setattr__ bypassed or construct via de_json().
This template uses the de_json approach which is the official PTB way.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram import Update
from telegram.ext import ContextTypes


def _make_update(text: str = "/start", user_id: int = 12345, username: str = "tester"):
    """Create a mock Update that works with PTB v20 (frozen objects).

    Uses de_json to construct a proper Update, then overrides the
    reply_text method with an AsyncMock for assertion testing.
    """
    data = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "text": text,
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": "Test",
                "username": username,
            },
            "chat": {
                "id": user_id,
                "type": "private",
            },
            "date": 1700000000,
        },
    }
    update = Update.de_json(data, MagicMock())
    update.message.reply_text = AsyncMock()
    return update


class TestCommands:
    """Test suite for bot commands."""

    @pytest.mark.asyncio
    async def test_start_command(self):
        """Test /start command sends welcome message."""
        from handlers.start import start

        update = _make_update("/start")
        context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)

        await start(update, context)

        update.message.reply_text.assert_called_once()
        response = update.message.reply_text.call_args[0][0]
        assert "welcome" in response.lower()

    @pytest.mark.asyncio
    async def test_help_command(self):
        """Test /help command lists available commands."""
        from handlers.help import help_command

        update = _make_update("/help")
        context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)

        await help_command(update, context)

        update.message.reply_text.assert_called_once()
        response = update.message.reply_text.call_args[0][0]
        assert "commands" in response.lower() or "available" in response.lower()

    @pytest.mark.asyncio
    async def test_status_command(self):
        """Test /status command shows bot status."""
        from handlers.status import status

        update = _make_update("/status")
        context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)

        await status(update, context)

        update.message.reply_text.assert_called_once()
        response = update.message.reply_text.call_args[0][0]
        assert "status" in response.lower() or "running" in response.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
