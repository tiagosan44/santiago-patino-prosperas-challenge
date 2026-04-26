"""FastAPI application entrypoint.

Exposes a minimal /health endpoint for now. Full router registration,
middleware, and dependency injection are added in subsequent tasks.
"""
from fastapi import FastAPI

app = FastAPI(
    title="Prosperas Reports API",
    version="0.1.0",
    description="Async report generation system — Prosperas technical challenge",
)


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy"}
