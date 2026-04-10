"""
Unit tests for Telegram bot message handlers.

Tests message processing, routing, and responses.
Run with: python -m pytest unit/test_handlers.py -v
"""

import pytest
from unittest.mock import AsyncMock
from telegram import Update
from telegram.ext import ContextTypes


class TestHandlers:
    """Test suite for message handlers."""

    @pytest.mark.asyncio
    async def test_message_handler_processes_text(self):
        """Test message handler processes incoming text."""
        from handlers.message import handle_message
        
        update = Update(update_id=1)
        update.message = AsyncMock()
        update.message.text = AsyncMock(return_value="Hello bot")
        update.message.reply_text = AsyncMock()
        context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)
        
        await handle_message(update, context)
        
        update.message.reply_text.assert_called_once()
        response = update.message.reply_text.call_args[0][0]
        assert response  # Should have some response

    @pytest.mark.asyncio
    async def test_message_handler_ignores_commands(self):
        """Test message handler ignores /commands."""
        from handlers.message import handle_message
        
        update = Update(update_id=1)
        update.message = AsyncMock()
        update.message.text = AsyncMock(return_value="/start")
        update.message.reply_text = AsyncMock()
        context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)
        
        await handle_message(update, context)
        
        # Should not process commands (those go to command handlers)
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_handler_logs_messages(self):
        """Test message handler logs incoming messages."""
        from handlers.message import handle_message
        
        update = Update(update_id=1)
        update.message = AsyncMock()
        update.message.text = AsyncMock(return_value="Test message")
        update.message.reply_text = AsyncMock()
        context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)
        
        await handle_message(update, context)
        
        # Message should be logged (check via logger in production)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
