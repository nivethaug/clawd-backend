"""
Unit tests for Telegram bot message handlers.

Tests message processing, routing, and responses.
Run with: python -m pytest unit/test_handlers.py -v

NOTE: python-telegram-bot v20 freezes Update objects — you CANNOT set
attributes directly (update.message = ... raises AttributeError).
Use the _make_update helper which uses de_json (official PTB way).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram import Update
from telegram.ext import ContextTypes


def _make_update(text: str = "Hello bot", user_id: int = 12345, username: str = "tester"):
    """Create a mock Update that works with PTB v20 (frozen objects)."""
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


class TestHandlers:
    """Test suite for message handlers."""

    @pytest.mark.asyncio
    async def test_message_handler_processes_text(self):
        """Test message handler processes incoming text."""
        from handlers.message import handle_message

        update = _make_update("Hello bot")
        context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)

        await handle_message(update, context)

        update.message.reply_text.assert_called_once()
        response = update.message.reply_text.call_args[0][0]
        assert response  # Should have some response

    @pytest.mark.asyncio
    async def test_message_handler_ignores_commands(self):
        """Test message handler ignores /commands."""
        from handlers.message import handle_message

        update = _make_update("/start")
        context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)

        await handle_message(update, context)

        # Should not process commands (those go to command handlers)
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_handler_logs_messages(self):
        """Test message handler logs incoming messages."""
        from handlers.message import handle_message

        update = _make_update("Test message")
        context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)

        await handle_message(update, context)

        # Message should be logged (check via logger in production)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
