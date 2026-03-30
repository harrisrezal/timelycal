import hmac
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from telegram import Update

logger = logging.getLogger(__name__)
router = APIRouter()

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")


def verify_admin(x_api_key: str = Header(...)):
    if not hmac.compare_digest(x_api_key, ADMIN_API_KEY):
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/telegram")
async def webhook(request: Request):
    token = request.headers.get("X-Telegram-Bot-API-Secret-Token", "")
    if not hmac.compare_digest(token, WEBHOOK_SECRET):
        return Response(status_code=403)
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
async def set_webhook(request: Request, _: None = Depends(verify_admin)):
    bot_app = request.app.state.bot_app
    webhook_url = str(request.base_url).replace("http://", "https://") + "webhook/telegram"
    result = await bot_app.bot.set_webhook(url=webhook_url, secret_token=WEBHOOK_SECRET)
    if result:
        return {"status": "ok", "webhook_url": webhook_url}
    return {"status": "error", "message": "Failed to set webhook"}


@router.get("/info")
async def webhook_info(request: Request, _: None = Depends(verify_admin)):
    bot_app = request.app.state.bot_app
    info = await bot_app.bot.get_webhook_info()
    return {
        "url": info.url,
        "pending_update_count": info.pending_update_count,
        "last_error_message": info.last_error_message,
    }
