"""Tests for global error format and request_id middleware."""
import pytest
from fastapi.testclient import TestClient

from app.core.aws import reset_clients
from app.main import app


@pytest.fixture
def client(users_table, jobs_table):
    """Minimal client; we don't need SQS/S3 for error tests."""
    from app.api import auth as auth_api
    from app.api import jobs as jobs_api

    reset_clients()
    app.dependency_overrides[auth_api.get_users_table] = lambda: users_table
    app.dependency_overrides[jobs_api.get_jobs_table] = lambda: jobs_table
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


# ---- request_id ----

def test_request_id_header_is_added_to_every_response(client):
    res = client.get("/health")
    assert res.status_code == 200
    rid = res.headers.get("X-Request-ID")
    assert rid is not None
    assert len(rid) >= 32  # uuid


def test_request_id_is_unique_per_request(client):
    r1 = client.get("/health").headers.get("X-Request-ID")
    r2 = client.get("/health").headers.get("X-Request-ID")
    assert r1 != r2


def test_request_id_uses_incoming_header_if_provided(client):
    res = client.get("/health", headers={"X-Request-ID": "client-supplied-12345678901234567890"})
    assert res.headers.get("X-Request-ID") == "client-supplied-12345678901234567890"


# ---- error envelope ----

def test_validation_error_returns_uniform_envelope(client):
    res = client.post("/auth/login", json={"username": "alice"})  # missing password
    assert res.status_code == 422
    body = res.json()
    assert body["error_code"] == "validation_error"
    assert "message" in body
    assert "request_id" in body
    assert "details" in body  # original validation errors retained


def test_http_exception_returns_uniform_envelope(client):
    res = client.post("/auth/login", json={"username": "alice", "password": "wrong"})
    assert res.status_code == 401
    body = res.json()
    assert body["error_code"] == "unauthorized"
    assert "message" in body
    assert "request_id" in body


def test_404_returns_uniform_envelope(client):
    res = client.get("/this-does-not-exist")
    assert res.status_code == 404
    body = res.json()
    assert body["error_code"] == "not_found"
    assert "request_id" in body


def test_internal_error_returns_uniform_envelope_500(client):
    """Force a generic Exception by overriding /health temporarily."""
    @app.get("/__broken__")
    def _broken():
        raise RuntimeError("boom")

    res = client.get("/__broken__")
    assert res.status_code == 500
    body = res.json()
    assert body["error_code"] == "internal_error"
    assert "request_id" in body
    # The actual exception detail should NOT leak to clients in this format
    assert "boom" not in body["message"].lower() or body["message"] == "internal server error"
