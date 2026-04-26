import asyncio
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from bot import get_application
from routes.telegram import router as telegram_router
from routes.upload import router as upload_router
from routes.query import router as query_router

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


async def _poll_and_broadcast(bot) -> None:
    """Fetch new Caltrain alerts and push to matching Telegram subscribers."""
    from services.alerts import get_new_alerts
    from services.announcements import get_telegram_subscribers

    try:
        new_alerts = await asyncio.to_thread(get_new_alerts)
        if not new_alerts:
            return
        subscribers = await asyncio.to_thread(get_telegram_subscribers)
        logger.info(f"Broadcasting {len(new_alerts)} alert(s) to {len(subscribers)} subscriber(s)")
        for sub in subscribers:
            chat_id = int(sub["platform_id"])
            sub_stations = sub["stations"] # list[str] or None (all stations)

            for alert in new_alerts:
                # Station filter: skip if none of the subscriber's stations are mentioned
                if sub_stations and alert["stations"] and not any(s in alert["stations"] for s in sub_stations):
                    continue
                try:
                    message_text = alert["text"]
                    if sub_stations and alert["stations"]:
                        from services.alerts import (
                            _extract_train_numbers, _get_train_stop_time,
                            _extract_delay_info, _add_minutes,
                        )
                        train_nums = _extract_train_numbers(alert["text"])
                        affected = [s for s in sub_stations if s in alert["stations"]]
                        if train_nums and affected:
                            delay_info = _extract_delay_info(alert["text"])
                            lines = []
                            for station in affected:
                                stop_time = await asyncio.to_thread(
                                    _get_train_stop_time, train_nums[0], station
                                )
                                if stop_time and delay_info:
                                    delay_label, delay_mins = delay_info
                                    est_time = _add_minutes(stop_time, delay_mins)
                                    lines.append(
                                        f"• {station} — sched. {stop_time}, now ~{est_time} (+{delay_label})"
                                    )
                                elif stop_time:
                                    lines.append(f"• {station} — sched. {stop_time}")
                                else:
                                    lines.append(f"• {station}")
                            if lines:
                                header = "ℹ️ Affects your station" + ("s" if len(lines) > 1 else "") + ":"
                                message_text += "\n\n" + header + "\n" + "\n".join(lines)
                    await bot.send_message(chat_id=chat_id, text=message_text)
                except Exception as e:
                    logger.warning(f"Failed to send alert to {chat_id}: {e}")
    except Exception as e:
        logger.error(f"Alert poll error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up: initializing Telegram bot...")
    app.state.bot_app = get_application()
    await app.state.bot_app.initialize()
    await app.state.bot_app.start()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(_poll_and_broadcast, "interval", minutes=5, args=[app.state.bot_app.bot])
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("Alert scheduler started (polling every 5 minutes)")

    yield

    logger.info("Shutting down: stopping scheduler and Telegram bot...")
    scheduler.shutdown(wait=False)
    await app.state.bot_app.stop()
    await app.state.bot_app.shutdown()


app = FastAPI(
    title="TimelyCal API",
    description="RAG-powered Caltrain schedule assistant",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_methods=["POST", "GET"],
)

app.include_router(telegram_router, prefix="/webhook")
app.include_router(upload_router, prefix="/admin")
app.include_router(query_router, prefix="/api")


@app.get("/")
async def health_check():
    return {"status": "ok", "message": "TimelyCal bot is running"}
