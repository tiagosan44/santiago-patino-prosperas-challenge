"""Centralized error envelope and exception handlers.

All errors that escape route handlers are converted into a uniform JSON
shape: `{error_code, message, request_id, details?}`. This shape is
consumed by the frontend's Toast component and matches what the spec
requires.

Why centralize:
- Frontend only has to handle one error shape.
- request_id always available for support diagnostics.
- Internal errors do NOT leak stack traces or sensitive details.
"""
import logging

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


_HTTP_CODE_TO_ERROR_CODE = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _envelope(*, error_code: str, message: str, request_id: str, details=None) -> dict:
    body = {"error_code": error_code, "message": message, "request_id": request_id}
    if details is not None:
        body["details"] = details
    return body


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=_envelope(
            error_code="validation_error",
            message="request payload failed validation",
            request_id=_request_id(request),
            details=exc.errors(),
        ),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    error_code = _HTTP_CODE_TO_ERROR_CODE.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else "http error"
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(
            error_code=error_code,
            message=message,
            request_id=_request_id(request),
        ),
        headers=getattr(exc, "headers", None),
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    rid = _request_id(request)
    # Server-side log keeps the full traceback; client never sees it.
    logger.exception("unhandled exception", extra={"request_id": rid})
    return JSONResponse(
        status_code=500,
        content=_envelope(
            error_code="internal_error",
            message="internal server error",
            request_id=rid,
        ),
    )
