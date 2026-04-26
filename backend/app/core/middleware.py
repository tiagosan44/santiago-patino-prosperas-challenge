"""Request-scoped middleware."""
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .logging_config import bind_request_context, clear_request_context


class RequestIDMiddleware(BaseHTTPMiddleware):
    HEADER = "X-Request-ID"

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get(self.HEADER) or str(uuid.uuid4())
        request.state.request_id = rid
        bind_request_context(request_id=rid)
        try:
            response = await call_next(request)
        finally:
            clear_request_context()
        response.headers[self.HEADER] = rid
        return response
