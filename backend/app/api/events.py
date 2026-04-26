"""Server-Sent Events endpoint and per-user pub/sub bus.

The 'bus' is an in-process registry mapping user_id -> set of
asyncio.Queues. When a Redis subscribe task dispatches an event for
user X, every queue registered for X receives a copy. The SSE
endpoint reads one user's queue and writes lines to the HTTP stream.

JWT travels via query string (?token=...) because the EventSource
browser API cannot send custom Authorization headers. The token is
the same JWT used for the /jobs API; in production we would mint a
short-lived SSE-only token in a separate exchange endpoint to limit
the blast radius if the URL is logged somewhere.

Heartbeat: every HEARTBEAT_SECONDS we emit ': keepalive\\n\\n' so that
intermediaries (ALB, proxies) do not close the idle TCP connection.
ALB default idle timeout is 60s; we send a heartbeat every 15s.
"""
import asyncio
import json
import logging
import queue
import threading
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from jose import JWTError

from ..core import security
from ..services import users as users_svc
from .auth import get_users_table

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])

# Configurable; tests patch this down.
HEARTBEAT_SECONDS: float = 15.0

# Poll interval: how long to sleep between queue checks.
# Short enough that disconnects are detected promptly.
_POLL_INTERVAL: float = 0.05


class _Bus:
    """In-process pub/sub registry: user_id -> set[queue.Queue].

    Uses threading.Lock + queue.Queue (both thread-safe) so that
    dispatch() can be called from any thread (test thread, Redis
    subscriber thread, etc.) safely.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[queue.Queue]] = {}
        self._lock = threading.Lock()

    def register_sync(self, user_id: str) -> "queue.Queue":
        q: queue.Queue = queue.Queue(maxsize=64)
        with self._lock:
            self._subscribers.setdefault(user_id, set()).add(q)
        return q

    def unregister_sync(self, user_id: str, q: "queue.Queue") -> None:
        with self._lock:
            queues = self._subscribers.get(user_id)
            if not queues:
                return
            queues.discard(q)
            if not queues:
                self._subscribers.pop(user_id, None)

    async def register(self, user_id: str) -> "queue.Queue":
        return self.register_sync(user_id)

    async def unregister(self, user_id: str, q: "queue.Queue") -> None:
        self.unregister_sync(user_id, q)

    def dispatch(self, event: dict) -> None:
        """Sync dispatch — used by the Redis subscriber task and tests.

        Drops events for users with full queues (slow consumers) rather
        than blocking the whole bus.
        """
        user_id = event.get("user_id")
        if user_id is None:
            return
        with self._lock:
            queues = set(self._subscribers.get(user_id) or ())
        for q in queues:
            try:
                q.put_nowait(event)
            except queue.Full:
                logger.warning(
                    "dropping event for user %s: queue full (slow consumer)", user_id
                )

    def reset_for_tests(self) -> None:
        with self._lock:
            self._subscribers.clear()


bus = _Bus()


def _resolve_user(token: Optional[str], table) -> str:
    """Returns user_id for a valid JWT, or raises 401."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing token"
        )
    try:
        payload = security.decode_access_token(token)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid token: {e}"
        ) from e
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    user = users_svc.get_by_username(table, username)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
    return user.user_id


async def _stream(request: Request, user_id: str) -> AsyncIterator[bytes]:
    """Async generator that yields SSE-formatted bytes for one user.

    Design:
    - Polls a thread-safe queue every _POLL_INTERVAL seconds.
    - Checks for client disconnect on each poll cycle.
    - Emits a keepalive comment every HEARTBEAT_SECONDS of inactivity.
    - try/finally ensures the queue is always unregistered on exit.
    """
    q = bus.register_sync(user_id)
    elapsed: float = 0.0
    try:
        # Initial comment confirms the connection is open
        yield b": connected\n\n"
        while True:
            # Check for events
            try:
                event = q.get_nowait()
            except queue.Empty:
                # No event — sleep briefly, check disconnect, then repeat
                await asyncio.sleep(_POLL_INTERVAL)
                # Check for disconnect after sleeping
                if await request.is_disconnected():
                    break
                elapsed += _POLL_INTERVAL
                if elapsed >= HEARTBEAT_SECONDS:
                    yield b": keepalive\n\n"
                    elapsed = 0.0
                continue
            # Got an event — reset heartbeat timer and forward it
            elapsed = 0.0
            data = json.dumps(event)
            yield f"event: job-update\ndata: {data}\n\n".encode()
    finally:
        bus.unregister_sync(user_id, q)


@router.get("/me")
async def stream_my_events(
    request: Request,
    token: Optional[str] = Query(None, description="JWT access token (EventSource cannot set headers)"),
    table=Depends(get_users_table),
):
    user_id = _resolve_user(token, table)
    return StreamingResponse(
        _stream(request, user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering if behind proxy
        },
    )
