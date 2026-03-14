import logging

from fastapi import APIRouter, Request, Response
from telegram import Update

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/telegram")
async def webhook(request: Request):
    try:
        data = await request.json()
        bot_app = request.app.state.bot_app
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"Error processing update: {e}")
        return Response(status_code=200)  # Always return 200 to Telegram


@router.get("/set-webhook")
async def set_webhook(request: Request):
    bot_app = request.app.state.bot_app
    webhook_url = str(request.base_url).replace("http://", "https://") + "webhook/telegram"
    result = await bot_app.bot.set_webhook(url=webhook_url)
    if result:
        return {"status": "ok", "webhook_url": webhook_url}
    return {"status": "error", "message": "Failed to set webhook"}


@router.get("/info")
async def webhook_info(request: Request):
    bot_app = request.app.state.bot_app
    info = await bot_app.bot.get_webhook_info()
    return {
        "url": info.url,
        "pending_update_count": info.pending_update_count,
        "last_error_message": info.last_error_message,
    }
