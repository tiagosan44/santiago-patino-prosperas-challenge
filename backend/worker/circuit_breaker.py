"""Distributed circuit breaker backed by Redis.

State per report_type lives in Redis hash circuit_breakers:{report_type}
with fields:
  - state: CLOSED | OPEN | HALF_OPEN  (CLOSED implicit when key absent)
  - failure_count: int  (only meaningful in CLOSED state)
  - opened_at: epoch seconds  (set when transitioned to OPEN)

Why distributed (not per-process): with multiple worker replicas, a
per-process breaker would multiply the failure threshold by replica
count before any single worker decided to open. Sharing the state
means the FIRST worker that sees N failures opens it for ALL workers.

Atomicity strategy: we use Redis WATCH + multi-exec (optimistic
transaction). The read-modify-write of failure_count + threshold
check is protected by watching the hash key. If another worker
modifies the key between our WATCH and EXEC, the transaction aborts
and we retry. This prevents the race where two workers both read
count=N-1, both increment to N, and neither opens the breaker.

NOTE: The ideal implementation uses a Lua script (single EVAL call),
which is fully atomic and avoids the retry loop. That approach
requires lupa (a Lua interpreter) to be available in fakeredis for
testing. In production (real Redis), Lua EVAL would be preferred and
the _run_lua helper below can be used by swapping the callers.

Public API: allow(client, report_type), record_success(...),
record_failure(...). Each accepts the redis client so callers can
inject a test client.
"""
import time
from typing import Final

import redis as redis_lib

# Tunables (constants for now; a Settings field could be added later).
FAILURE_THRESHOLD: Final[int] = 3
RECOVERY_SECONDS: Final[int] = 60

KEY_PREFIX = "circuit_breakers"

# Maximum retries on optimistic lock conflict in record_failure / record_success.
_MAX_RETRIES = 10


def _key(report_type: str) -> str:
    return f"{KEY_PREFIX}:{report_type}"


def allow(client, report_type: str) -> bool:
    """Return True if a request is allowed, False if the breaker is open.

    Side effect: when state is OPEN and recovery has elapsed, this
    transitions to HALF_OPEN and returns True (giving one trial
    request through).
    """
    key = _key(report_type)
    data = client.hgetall(key) or {}
    state = data.get("state", "CLOSED")

    if state == "CLOSED":
        return True

    if state == "HALF_OPEN":
        # Already in trial mode — let it through (the next outcome
        # closes or reopens the breaker).
        return True

    # state == OPEN
    opened_at = float(data.get("opened_at", 0))
    if time.time() - opened_at >= RECOVERY_SECONDS:
        # Transition to HALF_OPEN and let this one through.
        # Use WATCH + MULTI/EXEC so only one worker wins the transition.
        with client.pipeline() as pipe:
            for _ in range(_MAX_RETRIES):
                try:
                    pipe.watch(key)
                    current = pipe.hgetall(key) or {}
                    current_state = current.get("state", "CLOSED")
                    # Re-check: another worker may have already transitioned
                    if current_state != "OPEN":
                        pipe.reset()
                        return current_state in ("CLOSED", "HALF_OPEN")
                    opened_at_now = float(current.get("opened_at", 0))
                    if time.time() - opened_at_now < RECOVERY_SECONDS:
                        pipe.reset()
                        return False
                    pipe.multi()
                    pipe.hset(key, "state", "HALF_OPEN")
                    pipe.execute()
                    return True
                except redis_lib.WatchError:
                    continue
        # If we exhausted retries, check state again
        data2 = client.hgetall(key) or {}
        return data2.get("state", "CLOSED") in ("CLOSED", "HALF_OPEN")
    return False


def record_failure(client, report_type: str) -> None:
    """Increment failure count; open the breaker when threshold is reached.

    In HALF_OPEN state, immediately reopen the breaker (a probe failure
    means the service is still unhealthy).
    """
    key = _key(report_type)
    now = time.time()

    with client.pipeline() as pipe:
        for _ in range(_MAX_RETRIES):
            try:
                pipe.watch(key)
                data = pipe.hgetall(key) or {}
                state = data.get("state", "CLOSED")

                pipe.multi()

                if state == "HALF_OPEN":
                    # Probe failed — reopen immediately.
                    pipe.hset(key, mapping={"state": "OPEN", "opened_at": now})
                    pipe.execute()
                    return

                if state == "CLOSED":
                    count = int(data.get("failure_count", "0")) + 1
                    if count >= FAILURE_THRESHOLD:
                        pipe.hset(key, mapping={
                            "state": "OPEN",
                            "failure_count": count,
                            "opened_at": now,
                        })
                    else:
                        pipe.hset(key, "failure_count", count)
                    pipe.execute()
                    return

                # OPEN: already tripped, nothing to do.
                pipe.execute()
                return

            except redis_lib.WatchError:
                continue


def record_success(client, report_type: str) -> None:
    """Record a successful call.

    HALF_OPEN -> CLOSED (reset failure_count).
    CLOSED -> reset failure_count (clear transient failures).
    OPEN -> no-op (only allow() can transition out of OPEN).
    """
    key = _key(report_type)

    with client.pipeline() as pipe:
        for _ in range(_MAX_RETRIES):
            try:
                pipe.watch(key)
                data = pipe.hgetall(key) or {}
                state = data.get("state", "CLOSED")

                pipe.multi()

                if state == "HALF_OPEN":
                    pipe.hset(key, mapping={"state": "CLOSED", "failure_count": "0"})
                    pipe.hdel(key, "opened_at")
                    pipe.execute()
                    return

                if state == "CLOSED":
                    pipe.hset(key, "failure_count", "0")
                    pipe.execute()
                    return

                # OPEN: ignore success until allow() transitions to HALF_OPEN.
                pipe.execute()
                return

            except redis_lib.WatchError:
                continue
