"""FastAPI application entrypoint."""
import asyncio
import logging

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import auth, events, health as health_api, jobs
from .core import errors
from .core.config import get_settings
from .core.logging_config import configure_logging, get_logger
from .core.middleware import RequestIDMiddleware
from .services import realtime

configure_logging(service="api")
log = get_logger(__name__)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Prosperas Reports API",
    version="0.1.0",
    description="Async report generation system — Prosperas technical challenge",
)

app.add_middleware(RequestIDMiddleware)

app.add_exception_handler(RequestValidationError, errors.validation_exception_handler)
# Register on StarletteHTTPException to catch both Starlette and FastAPI HTTP exceptions
# (FastAPI's HTTPException is a subclass of StarletteHTTPException)
app.add_exception_handler(StarletteHTTPException, errors.http_exception_handler)
app.add_exception_handler(Exception, errors.unhandled_exception_handler)

app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(events.router)
app.include_router(health_api.router)


# ----- Redis -> SSE bus relay -----

_subscriber_task: asyncio.Task | None = None


async def _redis_to_bus_relay():
    """Background task: read Redis pub/sub stream and forward to SSE bus."""
    settings = get_settings()
    while True:
        try:
            async for event in realtime.subscribe(redis_url=settings.redis_url):
                events.bus.dispatch(event)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            # Reconnect on any other error after a short delay
            log.exception("redis_subscriber_crashed_reconnecting", retry_in_seconds=2)
            await asyncio.sleep(2)


@app.on_event("startup")
async def _start_subscriber():
    global _subscriber_task
    _subscriber_task = asyncio.create_task(_redis_to_bus_relay())


@app.on_event("shutdown")
async def _stop_subscriber():
    global _subscriber_task
    if _subscriber_task and not _subscriber_task.done():
        _subscriber_task.cancel()
        try:
            await _subscriber_task
        except asyncio.CancelledError:
            pass
