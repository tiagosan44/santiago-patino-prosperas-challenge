"""FastAPI application entrypoint."""
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import auth, jobs, events
from .core import errors
from .core.middleware import RequestIDMiddleware

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


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy"}
