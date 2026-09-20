"""
Telegram Bot Template - Main Entry Point (Webhook Mode)
Clean, minimal, AI-friendly structure.
Uses FastAPI for webhook handling with python-telegram-bot v20.
"""

import os
import uvicorn
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from dotenv import load_dotenv

from handlers.start import start
from handlers.help import help_command
from handlers.status import status
from handlers.message import handle_message
from utils.logger import logger
from core.database import init_db
from config import BOT_TOKEN, WEBHOOK_URL, WEBHOOK_PORT, SECRET_KEY

# ============================================================================
# Pydantic Models for API Documentation
# ============================================================================

class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    service: str


class BotInfoResponse(BaseModel):
    """Bot information response model."""
    message: str
    docs: str
    version: str


# Load environment variables
load_dotenv()

# Initialize FastAPI app — docs/OpenAPI DISABLED (public bots must not
# expose their API spec; set ENABLE_DOCS=true locally to develop against).
_DOCS = os.getenv("ENABLE_DOCS", "false").lower() in {"1", "true", "yes"}
app = FastAPI(
    title="Telegram Bot API",
    description="Telegram Bot Webhook and API Endpoints. Handles incoming Telegram updates and provides health/status endpoints.",
    version="1.0.0",
    docs_url="/docs" if _DOCS else None,
    redoc_url="/redoc" if _DOCS else None,
    openapi_url="/openapi.json" if _DOCS else None,
    openapi_tags=[
        {
            "name": "webhook",
            "description": "Telegram webhook endpoints for receiving updates"
        },
        {
            "name": "health",
            "description": "Health check and status endpoints"
        }
    ],
    contact={
        "name": "DreamAgent",
        "email": "support@dreamagent.cloud"
    },
    license_info={
        "name": "MIT"
    }
)

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
    # All commands route through ai_logic.py for AI customization.
    # filters.TEXT (not ALL): photos/stickers/voice have message.text=None
    # which would crash process_user_input — ignore non-text updates.
    bot_app.add_handler(MessageHandler(filters.TEXT, handle_message))


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

    # Check if webhook is already registered before overwriting it.
    # The platform registers the webhook during project creation with retries.
    # On PM2 restart (buildpublish), the bot runs inside a bwrap sandbox
    # where DNS may not resolve the webhook domain → set_webhook would fail
    # and clear the existing webhook. Only set if it's missing.
    if WEBHOOK_URL:
        try:
            # Check current webhook status first
            current = await bot_app.bot.get_webhook_info()
            current_url = getattr(current, "url", "") or ""

            if current_url == WEBHOOK_URL:
                logger.info(f"✅ Webhook already registered: {WEBHOOK_URL}")
            elif current_url:
                # Different webhook URL registered — update it
                logger.info(f"🔄 Updating webhook: {current_url} → {WEBHOOK_URL}")
                await bot_app.bot.set_webhook(url=WEBHOOK_URL)
                logger.info(f"✅ Webhook updated: {WEBHOOK_URL}")
            else:
                # No webhook registered — register now
                logger.info(f"🔗 Registering webhook: {WEBHOOK_URL}")
                await bot_app.bot.set_webhook(url=WEBHOOK_URL)
                logger.info(f"✅ Webhook set: {WEBHOOK_URL}")
        except Exception as e:
            logger.warning(f"⚠️ Webhook check/set failed (non-fatal — webhook may already be registered): {e}")
            logger.info(f"   If the bot doesn't respond, register manually:")
            logger.info(f"   curl -X POST 'https://api.telegram.org/bot$BOT_TOKEN/setWebhook?url={WEBHOOK_URL}'")
    else:
        logger.warning("⚠️ No WEBHOOK_URL configured - bot running in webhook mode without registration")
        logger.info("ℹ️ Set WEBHOOK_URL or WEBHOOK_DOMAIN environment variable to enable webhook")


@app.on_event("shutdown")
async def shutdown():
    """Shutdown event - cleanup (v20 lifecycle).

    NOTE: We do NOT delete the webhook on shutdown. PM2 restarts (buildpublish)
    trigger shutdown → startup cycles. Deleting the webhook here would clear
    the registration, and the startup re-registration might fail (DNS in
    sandbox), leaving the bot without a webhook. The platform manages webhook
    lifecycle — leave it registered across restarts.
    """
    if bot_app:
        try:
            await bot_app.stop()
            await bot_app.shutdown()
            logger.info("✅ Bot stopped (webhook left registered)")
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


@app.get("/")
async def root() -> BotInfoResponse:
    """Root endpoint with Pydantic model for Swagger."""
    return BotInfoResponse(
        message="Telegram Bot API",
        docs="",
        version="1.0.0"
    )


@app.get("/health")
async def health() -> HealthResponse:
    """Health check endpoint with Pydantic model for Swagger."""
    return HealthResponse(
        status="healthy",
        service="telegram-bot"
    )


@app.get("/")
async def root() -> BotInfoResponse:
    """Root endpoint with Pydantic model for Swagger."""
    return BotInfoResponse(
        message="Telegram Bot API",
        docs="",
        version="1.0.0"
    )


# ============================================================================
# Dev verifier — agent-facing synthetic invocation
# ============================================================================
# POST /dev/invoke exercises the SAME process_user_input() the webhook uses,
# in THIS deployed process (real DB, real env) and captures the reply without
# touching the Telegram API. Lets the platform agent verify changes end-to-end
# instead of guessing from logs. Gated by the project's own SECRET_KEY.
@app.post("/dev/invoke")
async def dev_invoke(request: Request):
    import json as _json
    import time as _time
    import hmac as _hmac

    supplied = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    if not SECRET_KEY or not _hmac.compare_digest(supplied, SECRET_KEY):
        return Response(
            content=_json.dumps({"ok": False, "error": "unauthorized"}),
            status_code=403,
            media_type="application/json",
        )

    try:
        body = await request.json()
    except Exception:
        return Response(
            content=_json.dumps({"ok": False, "error": "body must be JSON"}),
            status_code=400,
            media_type="application/json",
        )

    text = str(body.get("text") or "").strip()
    if not text:
        return Response(
            content=_json.dumps({"ok": False, "error": "text is required"}),
            status_code=400,
            media_type="application/json",
        )

    # Same user bootstrap as handlers/message.py (get-or-create), with the
    # same graceful fallback when the DB is unavailable.
    user = None
    try:
        from core.database import SessionLocal
        from utils.user_helpers import get_or_create_telegram_user
        db = SessionLocal()
        user = get_or_create_telegram_user(
            db=db,
            telegram_user_id=int(body.get("user_id") or 0),
            telegram_chat_id=int(body.get("chat_id") or body.get("user_id") or 0),
            telegram_username=str(body.get("username") or "verifier"),
        )
    except Exception as e:
        logger.warning(f"[dev-invoke] continuing without user context: {e}")

    started = _time.monotonic()
    try:
        from services.ai_logic import process_user_input
        response = process_user_input(text, user)
        return Response(
            content=_json.dumps({
                "ok": True,
                "response": str(response),
                "elapsed_ms": int((_time.monotonic() - started) * 1000),
            }),
            media_type="application/json",
        )
    except Exception as e:
        import traceback as _tb
        logger.error(f"[dev-invoke] invocation failed: {e}")
        return Response(
            content=_json.dumps({
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "trace": _tb.format_exc()[-1500:],
                "elapsed_ms": int((_time.monotonic() - started) * 1000),
            }),
            status_code=200,  # transport OK; the invocation failed — return details
            media_type="application/json",
        )


if __name__ == "__main__":
    # Run FastAPI server
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=WEBHOOK_PORT,
        reload=False,
        log_level="info"
    )
