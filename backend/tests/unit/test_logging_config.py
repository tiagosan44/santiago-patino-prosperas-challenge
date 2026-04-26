"""Tests for the structlog configuration.

We can't easily assert the exact JSON output (timestamps vary), but
we can verify that the log records produced are dictionaries with
the expected keys.
"""
import io
import json
import logging

import pytest

from app.core import logging_config


@pytest.fixture
def captured_stdout(monkeypatch):
    buf = io.StringIO()

    # Re-configure with our buffer instead of sys.stdout
    monkeypatch.setattr("sys.stdout", buf)
    logging_config.configure_logging(service="test")
    yield buf
    # Reset for other tests
    logging_config.clear_request_context()


def _read_lines(buf: io.StringIO) -> list[dict]:
    raw = buf.getvalue()
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def test_configure_logging_emits_json(captured_stdout):
    log = logging_config.get_logger("t")
    log.info("test_event", k="v")
    lines = _read_lines(captured_stdout)
    assert any(l.get("event") == "test_event" and l.get("k") == "v" for l in lines)


def test_logging_includes_service_field(captured_stdout):
    log = logging_config.get_logger("t")
    log.info("hello")
    lines = _read_lines(captured_stdout)
    assert any(l.get("service") == "test" for l in lines)


def test_bind_request_context_propagates_to_log_lines(captured_stdout):
    logging_config.bind_request_context(request_id="rid-123")
    log = logging_config.get_logger("t")
    log.info("event_with_rid")
    logging_config.clear_request_context()

    lines = _read_lines(captured_stdout)
    assert any(l.get("request_id") == "rid-123" and l.get("event") == "event_with_rid" for l in lines)


def test_clear_context_removes_request_id(captured_stdout):
    logging_config.bind_request_context(request_id="rid-to-clear")
    logging_config.clear_request_context()
    log = logging_config.get_logger("t")
    log.info("after_clear")

    lines = _read_lines(captured_stdout)
    after = [l for l in lines if l.get("event") == "after_clear"]
    assert after, f"no 'after_clear' line in {lines!r}"
    assert all("request_id" not in l for l in after)
