import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from bot import get_application
from routes.telegram import router as telegram_router
from routes.upload import router as upload_router
from routes.query import router as query_router

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up: initializing Telegram bot...")
    app.state.bot_app = get_application()
    await app.state.bot_app.initialize()
    await app.state.bot_app.start()
    yield
    logger.info("Shutting down: stopping Telegram bot...")
    await app.state.bot_app.stop()
    await app.state.bot_app.shutdown()


app = FastAPI(
    title="TimelyCal API",
    description="RAG-powered Caltrain schedule assistant",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(telegram_router, prefix="/webhook")
app.include_router(upload_router, prefix="/admin")
app.include_router(query_router, prefix="/api")


@app.get("/")
async def health_check():
    return {"status": "ok", "message": "TimelyCal bot is running"}
