"""Request-scoped middleware.

Attaches a UUID `request_id` to every incoming request and surfaces it
in the `X-Request-ID` response header. Honors the same incoming header
if the client supplied one (useful for tracing through gateways).
"""
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class RequestIDMiddleware(BaseHTTPMiddleware):
    HEADER = "X-Request-ID"

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get(self.HEADER) or str(uuid.uuid4())
        request.state.request_id = rid
        response = await call_next(request)
        response.headers[self.HEADER] = rid
        return response
