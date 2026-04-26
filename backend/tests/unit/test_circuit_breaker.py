"""Unit tests for the Redis-backed circuit breaker.

Uses fakeredis. The Lua atomicity is exercised by the underlying
fakeredis-py implementation, which supports EVAL.
"""
import time
from unittest.mock import patch

import fakeredis
import pytest

from worker import circuit_breaker as cb


@pytest.fixture
def redis_client():
    return fakeredis.FakeStrictRedis(decode_responses=True)


# ---- defaults / thresholds ----

def test_initial_state_allows(redis_client):
    """A fresh report_type with no breaker entry is implicitly CLOSED."""
    assert cb.allow(redis_client, "sales") is True


def test_record_success_under_threshold_keeps_closed(redis_client):
    cb.record_success(redis_client, "sales")
    cb.record_success(redis_client, "sales")
    assert cb.allow(redis_client, "sales") is True


# ---- opening on failures ----

def test_record_failure_below_threshold_stays_closed(redis_client):
    cb.record_failure(redis_client, "sales")
    cb.record_failure(redis_client, "sales")
    assert cb.allow(redis_client, "sales") is True


def test_record_failure_at_threshold_opens(redis_client):
    cb.record_failure(redis_client, "sales")
    cb.record_failure(redis_client, "sales")
    cb.record_failure(redis_client, "sales")
    assert cb.allow(redis_client, "sales") is False


def test_open_breaker_blocks(redis_client):
    for _ in range(3):
        cb.record_failure(redis_client, "sales")
    # A separate report_type is unaffected
    assert cb.allow(redis_client, "audit") is True
    assert cb.allow(redis_client, "sales") is False


# ---- half-open transition after recovery ----

def test_open_to_half_open_after_recovery_period(redis_client):
    for _ in range(3):
        cb.record_failure(redis_client, "sales")
    assert cb.allow(redis_client, "sales") is False

    # Time-travel: pretend we're past the recovery window
    with patch("worker.circuit_breaker.time.time", return_value=time.time() + 61):
        # First call after recovery transitions to HALF_OPEN and returns True
        assert cb.allow(redis_client, "sales") is True


def test_half_open_success_closes_breaker(redis_client):
    for _ in range(3):
        cb.record_failure(redis_client, "sales")

    with patch("worker.circuit_breaker.time.time", return_value=time.time() + 61):
        cb.allow(redis_client, "sales")  # transitions to HALF_OPEN
        cb.record_success(redis_client, "sales")  # closes breaker

    # Back to CLOSED — failure_count reset
    assert cb.allow(redis_client, "sales") is True
    cb.record_failure(redis_client, "sales")
    assert cb.allow(redis_client, "sales") is True  # only 1 failure, well below threshold


def test_half_open_failure_reopens_breaker(redis_client):
    for _ in range(3):
        cb.record_failure(redis_client, "sales")

    t0 = time.time()
    with patch("worker.circuit_breaker.time.time", return_value=t0 + 61):
        cb.allow(redis_client, "sales")  # transitions to HALF_OPEN
        cb.record_failure(redis_client, "sales")  # back to OPEN

    # Still blocked even right after
    with patch("worker.circuit_breaker.time.time", return_value=t0 + 62):
        assert cb.allow(redis_client, "sales") is False


# ---- per-report-type isolation ----

def test_breakers_are_isolated_per_report_type(redis_client):
    for _ in range(3):
        cb.record_failure(redis_client, "sales")
    assert cb.allow(redis_client, "sales") is False
    assert cb.allow(redis_client, "audit") is True
    assert cb.allow(redis_client, "inventory") is True
