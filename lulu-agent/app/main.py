from __future__ import annotations

"""LuLu Agent FastAPI entry: uvicorn app.main:app"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.api.rtc_llm import router as rtc_router
from app.core.bootstrap import init_db
from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def _warmup() -> None:
    if get_settings().ai_provider.strip().lower() == "mock":
        return
    try:
        from app.services.asr import recognize_pcm16

        await recognize_pcm16(b"\x00\x00" * 3200, "wake")
        logger.info("asr warmup done")
    except Exception as exc:
        logger.warning("asr warmup: %s", exc)
    try:
        from app.services.voice import VoiceService

        await asyncio.to_thread(VoiceService().warmup)
        logger.info("tts warmup done (keepalive + greet cache)")
    except Exception as exc:
        logger.warning("tts warmup: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    loop_task: asyncio.Task | None = None
    optimizer_loop = None
    if settings.memory_backend == "akashic" and settings.akashic_optimizer_enabled:
        from app.memory.optimizer_runtime import MultiPersonOptimizerLoop

        optimizer_loop = MultiPersonOptimizerLoop(
            interval_seconds=settings.akashic_optimizer_interval_seconds
        )
        loop_task = asyncio.create_task(optimizer_loop.run())
        app.state.memory_optimizer_loop = optimizer_loop
        logger.info("MemoryOptimizerLoop 已挂载")
    asyncio.create_task(_warmup())
    try:
        yield
    finally:
        if optimizer_loop is not None:
            optimizer_loop.stop()
        if loop_task is not None:
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(
        title="LuLu Agent",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(router, prefix="/api")
    app.include_router(rtc_router, prefix="/api")
    app.include_router(router)
    app.include_router(rtc_router)

    @app.get("/")
    def index():
        return {"status": "UP", "service": "lulu-agent"}

    return app


app = create_app()
