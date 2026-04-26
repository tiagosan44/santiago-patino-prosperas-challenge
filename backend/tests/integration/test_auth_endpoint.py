"""Integration tests for /auth/login.

Uses FastAPI's TestClient with the moto-backed users_table fixture.
The conftest's env vars are set before app import so Settings()
validation succeeds.
"""
from fastapi.testclient import TestClient

from app.core import security
from app.core.aws import reset_clients
from app.main import app
from app.services import users as users_svc


def _client(users_table) -> TestClient:
    """Return a TestClient with users_table dependency override."""
    from app.api.auth import get_users_table

    reset_clients()
    app.dependency_overrides[get_users_table] = lambda: users_table
    return TestClient(app)


def test_login_returns_jwt_on_valid_credentials(users_table):
    users_svc.create_user(users_table, "alice", "secret123")
    client = _client(users_table)

    res = client.post("/auth/login", json={"username": "alice", "password": "secret123"})
    assert res.status_code == 200
    data = res.json()
    assert data["token_type"] == "bearer"
    assert "access_token" in data

    payload = security.decode_access_token(data["access_token"])
    assert payload["sub"] == "alice"


def test_login_returns_401_on_wrong_password(users_table):
    users_svc.create_user(users_table, "alice", "secret123")
    client = _client(users_table)

    res = client.post("/auth/login", json={"username": "alice", "password": "WRONG"})
    assert res.status_code == 401


def test_login_returns_401_on_unknown_user(users_table):
    client = _client(users_table)

    res = client.post("/auth/login", json={"username": "ghost", "password": "anypass"})
    assert res.status_code == 401


def test_login_validates_payload_shape(users_table):
    client = _client(users_table)

    # Missing password
    res = client.post("/auth/login", json={"username": "alice"})
    assert res.status_code == 422

    # Empty username
    res = client.post("/auth/login", json={"username": "", "password": "secret123"})
    assert res.status_code == 422
