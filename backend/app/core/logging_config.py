"""structlog configuration for the API and the worker.

Output is JSON to stdout. Each log line includes:
  - timestamp (ISO 8601, UTC)
  - level
  - service ('api' or 'worker')
  - request_id (when bound by middleware)
  - event (the log message itself)
  - any structured kwargs the caller passed

Usage:
  from app.core.logging_config import configure_logging, get_logger
  configure_logging(service='api')
  log = get_logger(__name__)
  log.info('event_name', user_id='u-1', job_id='j-1')

Why structlog over stdlib JSON formatters: structlog lets you bind
context (e.g. request_id) once via a contextvar and have every
subsequent log line within that request automatically include it,
without each log call having to pass it explicitly.
"""
import logging
import sys
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, merge_contextvars

from .config import get_settings


def configure_logging(service: str = "api") -> None:
    """Idempotent: safe to call from multiple entrypoints."""
    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Wrap stdlib logging so libraries (boto3, uvicorn) also emit JSON.
    # force=True removes pre-existing handlers so the stream is always
    # the current sys.stdout — this is important for test isolation
    # where monkeypatch.setattr replaces sys.stdout before calling
    # configure_logging().
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
        force=True,
    )

    structlog.configure(
        processors=[
            merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # Must be False so that reconfiguration in tests (with a new
        # stdout buffer) takes effect on every log call.
        cache_logger_on_first_use=False,
    )

    # Bind service tag globally
    bind_contextvars(service=service)


def get_logger(name: str | None = None):
    """Return a structlog BoundLogger."""
    return structlog.get_logger(name)


def bind_request_context(**kwargs: Any) -> None:
    """Bind values to the contextvars for the current async/request scope."""
    bind_contextvars(**kwargs)


def clear_request_context() -> None:
    clear_contextvars()
