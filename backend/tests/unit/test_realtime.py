"""Unit tests for the realtime (Redis pub/sub) helpers.

Uses fakeredis for the sync publish path (deterministic, no docker
network needed). The async subscribe path is exercised via a real
Redis connection in the integration test below.
"""
import asyncio
import json

import pytest

from app.services import realtime


# ---- publish_event ----

def test_publish_event_serializes_to_json():
    import fakeredis
    r = fakeredis.FakeStrictRedis()

    # Subscribe synchronously to verify the published payload
    pubsub = r.pubsub()
    pubsub.subscribe(realtime.CHANNEL)
    # Drain the subscribe-confirmation message
    pubsub.get_message(timeout=1)

    realtime.publish_event(r, {"job_id": "j-1", "status": "COMPLETED"})

    msg = pubsub.get_message(timeout=1)
    assert msg is not None
    data = msg["data"]
    if isinstance(data, bytes):
        data = data.decode()
    body = json.loads(data)
    assert body == {"job_id": "j-1", "status": "COMPLETED"}


def test_publish_event_returns_subscriber_count():
    import fakeredis
    r = fakeredis.FakeStrictRedis()

    # No subscribers
    assert realtime.publish_event(r, {"x": 1}) == 0

    # One subscriber
    pubsub = r.pubsub()
    pubsub.subscribe(realtime.CHANNEL)
    pubsub.get_message(timeout=1)  # drain confirmation
    assert realtime.publish_event(r, {"x": 1}) == 1


# ---- subscribe (async) ----

@pytest.mark.asyncio
async def test_subscribe_yields_published_events():
    """Integration test using real Redis. Skipped if Redis is not reachable."""
    import redis.asyncio as aioredis
    from os import environ

    url = environ.get("REDIS_URL", "redis://localhost:6379/0")

    # Quick reachability check; skip on CI without Redis
    sync_r = None
    try:
        import redis as sync_redis
        sync_r = sync_redis.from_url(url, socket_connect_timeout=1)
        sync_r.ping()
    except Exception:
        pytest.skip(f"Redis not reachable at {url}")

    received: list[dict] = []

    async def collect():
        async for event in realtime.subscribe(redis_url=url):
            received.append(event)
            if len(received) >= 2:
                break

    task = asyncio.create_task(collect())
    # Give the subscriber a moment to register
    await asyncio.sleep(0.2)

    # Publish two events from a separate sync client
    sync_r.publish(realtime.CHANNEL, json.dumps({"job_id": "a", "status": "PROCESSING"}))
    sync_r.publish(realtime.CHANNEL, json.dumps({"job_id": "b", "status": "COMPLETED"}))

    # Wait for collection (with timeout)
    try:
        await asyncio.wait_for(task, timeout=3)
    except asyncio.TimeoutError:
        task.cancel()
        pytest.fail("subscribe did not yield events within 3s")

    assert {e["job_id"] for e in received} == {"a", "b"}


# ---- subscribe ignores non-JSON messages ----

@pytest.mark.asyncio
async def test_subscribe_skips_non_json_messages():
    """Robustness: a malformed message must not crash the subscriber."""
    import redis.asyncio as aioredis
    import redis as sync_redis
    from os import environ

    url = environ.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        sync_r = sync_redis.from_url(url, socket_connect_timeout=1)
        sync_r.ping()
    except Exception:
        pytest.skip(f"Redis not reachable at {url}")

    received: list[dict] = []

    async def collect():
        async for event in realtime.subscribe(redis_url=url):
            received.append(event)
            if len(received) >= 1:
                break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.2)

    sync_r.publish(realtime.CHANNEL, "not-json-at-all")
    sync_r.publish(realtime.CHANNEL, json.dumps({"job_id": "valid"}))

    try:
        await asyncio.wait_for(task, timeout=3)
    except asyncio.TimeoutError:
        task.cancel()
        pytest.fail("did not skip bad message")

    assert received == [{"job_id": "valid"}]
