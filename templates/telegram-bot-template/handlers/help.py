"""
Help command handler.
Shows available commands and examples.
"""


async def help_command(update, context):
    """Handle /help command."""
    await update.message.reply_text(
        "💡 *Available Commands*\n\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n\n"
        "💡 *Try asking:*\n"
        "• BTC price\n"
        "• Weather in city\n"
        "• Any simple task\n\n"
        "🤖 I'm here to help!",
        parse_mode="Markdown"
    )
