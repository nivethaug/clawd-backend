"""
Telegram Bot Template - Main Entry Point (Webhook Mode)
Clean, minimal, AI-friendly structure.
Uses FastAPI for webhook handling with python-telegram-bot v20.
"""

import os
import uvicorn
from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from dotenv import load_dotenv

from handlers.start import start
from handlers.help import help_command
from handlers.message import handle_message
from utils.logger import logger
from core.database import init_db
from config import BOT_TOKEN, WEBHOOK_URL, WEBHOOK_PORT

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="Telegram Bot API")

# Initialize Telegram bot application
bot_app = None


def init_bot():
    """Initialize Telegram bot with handlers."""
    global bot_app
    
    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN not found in environment variables")

    logger.info("🚀 Initializing Telegram bot...")

    # Initialize database tables (optional - won't crash if no DB)
    try:
        init_db()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.warning(f"⚠️ Database initialization skipped: {e}")

    # Build bot application (v20 API)
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register handlers
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("✅ Bot application built successfully")


@app.on_event("startup")
async def startup():
    """Startup event - initialize bot and set webhook (v20 lifecycle)."""
    global bot_app
    
    # Build the bot application
    init_bot()
    
    # v20 requires explicit initialize() and start()
    await bot_app.initialize()
    await bot_app.start()
    
    # Set webhook on Telegram servers
    if WEBHOOK_URL:
        try:
            await bot_app.bot.set_webhook(url=WEBHOOK_URL)
            logger.info(f"✅ Webhook set: {WEBHOOK_URL}")
        except Exception as e:
            logger.error(f"❌ Failed to set webhook: {e}")
    else:
        logger.warning("⚠️ No WEBHOOK_URL configured")


@app.on_event("shutdown")
async def shutdown():
    """Shutdown event - cleanup (v20 lifecycle)."""
    if bot_app:
        try:
            await bot_app.stop()
            await bot_app.shutdown()
            await bot_app.bot.delete_webhook()
            logger.info("✅ Bot stopped and webhook removed")
        except Exception as e:
            logger.error(f"❌ Shutdown error: {e}")


@app.post("/webhook")
async def webhook_handler(request: Request):
    """Handle incoming webhook updates from Telegram."""
    try:
        # Parse update
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        
        # Process update
        await bot_app.process_update(update)
        
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return Response(status_code=500)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "telegram-bot"}


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Telegram Bot API", "docs": "/docs"}


if __name__ == "__main__":
    # Run FastAPI server
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=WEBHOOK_PORT,
        reload=False,
        log_level="info"
    )
