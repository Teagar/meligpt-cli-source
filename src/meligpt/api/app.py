from __future__ import annotations

import asyncio
import contextlib

from fastapi import FastAPI

from meligpt.api.openai_compat import build_openai_router
from meligpt.api.routes import build_chat_router, router
from meligpt.auth.refresher import run_auto_refresh_loop
from meligpt.config import Settings
from meligpt.logging import configure_logging, get_logger
from meligpt.tools.registry import build_default_registry

_logger = get_logger("api.app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)
    registry = build_default_registry()

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        refresh_task: asyncio.Task | None = None
        if settings.auto_refresh_enabled:
            refresh_task = asyncio.create_task(run_auto_refresh_loop(settings))
            _logger.info("loop de refresh automático de token iniciado")
        try:
            yield
        finally:
            if refresh_task is not None:
                refresh_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await refresh_task

    app = FastAPI(
        title="MeliGPT CLI — servidor HTTP/SSE opcional",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.include_router(router)
    app.include_router(build_chat_router(settings, registry))
    app.include_router(build_openai_router(settings, registry))
    return app
