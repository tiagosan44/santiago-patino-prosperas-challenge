"""Integration tests for the SSE /events/me endpoint.

These tests mostly exercise the bus + endpoint plumbing. They do NOT
need real Redis; they use a fake bus that exposes the same publish/
subscribe interface but stays in-process.

Sync TestClient works for status-code-only checks (401 before body).
Tests that need actual SSE streaming use a direct ASGI invocation via
anyio task groups, which allow true concurrent streaming without
buffering the entire response body first.
"""
import asyncio
import json

import anyio
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.core import security
from app.core.aws import reset_clients
from app.main import app
from app.services import users as users_svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_http_scope(path: str, query: str = "") -> dict:
    return {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "scheme": "http",
        "query_string": query.encode(),
        "headers": [],
        "client": ["testclient", 50000],
        "server": ["testserver", 80],
    }


async def _collect_sse_events(
    token: str,
    stop_condition,
    dispatch_fn=None,
    timeout: float = 5.0,
) -> str:
    """Helper: run the SSE ASGI app in a background task, collect SSE text.

    Args:
        token: JWT access token (sent as ?token=...).
        stop_condition: callable(buf: str) -> bool — return True to stop.
        dispatch_fn: optional callable called once after stream opens.
        timeout: max seconds to wait.
    Returns:
        Collected SSE text.
    """
    scope = _make_http_scope("/events/me", f"token={token}")
    buf = []
    response_started = asyncio.Event()
    disconnect_event = asyncio.Event()

    async def receive():
        await disconnect_event.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            response_started.set()
        elif message["type"] == "http.response.body":
            body = message.get("body", b"")
            if body:
                buf.append(body.decode("utf-8", errors="replace"))

    async def drive():
        await response_started.wait()
        if dispatch_fn is not None:
            dispatch_fn()
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            text = "".join(buf)
            if stop_condition(text):
                return text
            await asyncio.sleep(0.02)
        return "".join(buf)

    async with anyio.create_task_group() as tg:
        tg.start_soon(app, scope, receive, send)
        result = await drive()
        disconnect_event.set()
        tg.cancel_scope.cancel()

    return result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client_setup(users_table, jobs_table):
    """Wire moto-backed tables and reset SSE bus state."""
    from app.api import auth as auth_api
    from app.api import jobs as jobs_api
    from app.api import events as events_api

    reset_clients()
    app.dependency_overrides[auth_api.get_users_table] = lambda: users_table
    app.dependency_overrides[jobs_api.get_jobs_table] = lambda: jobs_table
    # Reset the in-process subscriber registry between tests
    events_api.bus.reset_for_tests()
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_events_endpoint_rejects_missing_token(client_setup):
    with TestClient(app) as client:
        # No token — must 401 before opening the stream
        with client.stream("GET", "/events/me") as r:
            assert r.status_code == 401


def test_events_endpoint_rejects_invalid_token(client_setup):
    with TestClient(app) as client:
        with client.stream("GET", "/events/me?token=not-a-real-jwt") as r:
            assert r.status_code == 401


@pytest.mark.asyncio
async def test_events_endpoint_streams_event_for_authenticated_user(users_table, client_setup):
    from app.api import events as events_api
    user = users_svc.create_user(users_table, "alice", "secret123")
    token = security.create_access_token(subject=user.username)

    def dispatch():
        events_api.bus.dispatch({
            "job_id": "j-1",
            "user_id": user.user_id,
            "status": "PROCESSING",
        })

    buf = await _collect_sse_events(
        token=token,
        stop_condition=lambda text: "data:" in text and "\n\n" in text,
        dispatch_fn=dispatch,
        timeout=5.0,
    )

    assert "event: job-update" in buf
    data_line = next(
        (line for line in buf.splitlines() if line.startswith("data:")), None
    )
    assert data_line is not None
    payload = json.loads(data_line[len("data:"):].strip())
    assert payload["job_id"] == "j-1"
    assert payload["status"] == "PROCESSING"


@pytest.mark.asyncio
async def test_events_endpoint_only_streams_to_matching_user(users_table, client_setup):
    """Events for user B must NOT reach user A's stream."""
    from app.api import events as events_api
    alice = users_svc.create_user(users_table, "alice", "secret123")
    bob = users_svc.create_user(users_table, "bob", "secret123")
    alice_token = security.create_access_token(subject=alice.username)

    def dispatch():
        events_api.bus.dispatch({
            "job_id": "j-bob", "user_id": bob.user_id, "status": "PROCESSING",
        })
        events_api.bus.dispatch({
            "job_id": "j-alice", "user_id": alice.user_id, "status": "PROCESSING",
        })

    buf = await _collect_sse_events(
        token=alice_token,
        stop_condition=lambda text: "j-alice" in text,
        dispatch_fn=dispatch,
        timeout=5.0,
    )

    assert "j-alice" in buf
    assert "j-bob" not in buf  # would be a privacy leak


def test_bus_dispatch_with_no_subscribers_does_not_raise(client_setup):
    """Hardening: dispatching for a user with no open SSE must be a no-op."""
    from app.api import events as events_api
    events_api.bus.dispatch({"job_id": "j-1", "user_id": "u-no-listeners", "status": "X"})


@pytest.mark.asyncio
async def test_sse_emits_keepalive_comment_periodically(users_table, client_setup):
    """Heartbeat (keepalive comment) is emitted within the configured interval.

    We monkey-patch the heartbeat interval down to 0.1s for speed.
    """
    from app.api import events as events_api
    user = users_svc.create_user(users_table, "alice", "secret123")
    token = security.create_access_token(subject=user.username)

    # Force a tiny heartbeat for the test
    original = events_api.HEARTBEAT_SECONDS
    events_api.HEARTBEAT_SECONDS = 0.1
    try:
        buf = await _collect_sse_events(
            token=token,
            stop_condition=lambda text: "keepalive" in text,
            dispatch_fn=None,
            timeout=1.5,
        )
        if "keepalive" not in buf:
            pytest.fail(f"no keepalive seen in 1.5s, buf={buf!r}")
    finally:
        events_api.HEARTBEAT_SECONDS = original
