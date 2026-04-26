"""FastAPI application entrypoint."""
from fastapi import FastAPI

from .api import auth

app = FastAPI(
    title="Prosperas Reports API",
    version="0.1.0",
    description="Async report generation system — Prosperas technical challenge",
)

app.include_router(auth.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy"}
