"""
Unit tests for Telegram bot command handlers.

Tests command registration, execution, and responses.
Run with: python -m pytest unit/test_commands.py -v
"""

import pytest
from unittest.mock import AsyncMock, patch
from telegram import Update
from telegram.ext import ContextTypes


class TestCommands:
    """Test suite for bot commands."""

    @pytest.mark.asyncio
    async def test_start_command(self):
        """Test /start command sends welcome message."""
        from handlers.start import start
        
        # Create mock update with user
        update = Update(update_id=1)
        update.message = AsyncMock()
        update.message.reply_text = AsyncMock()
        
        # Create mock context
        context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)
        
        # Run command
        await start(update, context)
        
        # Verify response
        update.message.reply_text.assert_called_once()
        response = update.message.reply_text.call_args[0][0]
        assert "welcome" in response.lower()

    @pytest.mark.asyncio
    async def test_help_command(self):
        """Test /help command lists available commands."""
        from handlers.help import help_command
        
        update = Update(update_id=1)
        update.message = AsyncMock()
        update.message.reply_text = AsyncMock()
        context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)
        
        await help_command(update, context)
        
        update.message.reply_text.assert_called_once()
        response = update.message.reply_text.call_args[0][0]
        assert "commands" in response.lower() or "available" in response.lower()

    @pytest.mark.asyncio
    async def test_status_command(self):
        """Test /status command shows bot status."""
        from handlers.status import status
        
        update = Update(update_id=1)
        update.message = AsyncMock()
        update.message.reply_text = AsyncMock()
        context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)
        
        await status(update, context)
        
        update.message.reply_text.assert_called_once()
        response = update.message.reply_text.call_args[0][0]
        assert "status" in response.lower() or "running" in response.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
