"""Redis pub/sub helpers for real-time job-update fan-out.

Publishes go through the sync redis client (used by the synchronous
worker and the SNS handler). Subscribes use redis.asyncio because the
SSE endpoint must yield messages without blocking the event loop.

Wire format: each message body is a JSON-encoded dict. The minimum
shape is `{job_id, user_id, status, ...}` but the helpers do not
enforce a schema — anything JSON-encodable goes.
"""
import json
import logging
from typing import AsyncIterator

import redis as sync_redis
import redis.asyncio as aioredis

from ..core.config import get_settings

logger = logging.getLogger(__name__)


CHANNEL = "job-updates"


def get_redis_client():
    """Sync Redis client for the publisher path. Caller manages lifetime."""
    settings = get_settings()
    return sync_redis.from_url(settings.redis_url, decode_responses=True)


def publish_event(client, payload: dict) -> int:
    """Serialize the payload and publish to CHANNEL.

    Returns the number of subscribers that received the message.
    """
    body = json.dumps(payload)
    return int(client.publish(CHANNEL, body))


async def subscribe(redis_url: str | None = None) -> AsyncIterator[dict]:
    """Async iterator over decoded job-update events.

    Skips messages whose payload is not valid JSON (logs a warning).
    The caller is responsible for cancelling the iterator on shutdown.
    """
    if redis_url is None:
        redis_url = get_settings().redis_url

    client = aioredis.from_url(redis_url, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(CHANNEL)
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue  # subscribe-confirmations etc.
            try:
                yield json.loads(message["data"])
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "skipping non-JSON pub/sub message on %s: %r",
                    CHANNEL,
                    message.get("data"),
                )
                continue
    finally:
        try:
            await pubsub.unsubscribe(CHANNEL)
            await pubsub.aclose()
            await client.aclose()
        except Exception:  # noqa: BLE001
            logger.exception("error closing Redis pubsub")
