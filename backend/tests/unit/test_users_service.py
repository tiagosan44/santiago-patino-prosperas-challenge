"""Tests for the users service.

Validates user creation (with bcrypt hashing), lookup by username
(via the username-index GSI), and authentication (constant-time
password verification).
"""
import pytest

from app.services import users as users_svc


def test_create_user_persists_with_uuid_and_hashed_password(users_table):
    user = users_svc.create_user(users_table, "alice", "secret123")
    assert user.username == "alice"
    assert user.user_id  # non-empty
    assert "-" in user.user_id  # looks like a UUID
    assert user.password_hash != "secret123"  # actually hashed
    assert user.password_hash.startswith("$2b$") or user.password_hash.startswith("$2a$")  # bcrypt format


def test_create_user_persists_to_table(users_table):
    user = users_svc.create_user(users_table, "alice", "secret123")
    item = users_table.get_item(Key={"user_id": user.user_id}).get("Item")
    assert item is not None
    assert item["username"] == "alice"


def test_create_user_rejects_duplicate_username(users_table):
    users_svc.create_user(users_table, "alice", "secret123")
    with pytest.raises(users_svc.UsernameAlreadyExistsError):
        users_svc.create_user(users_table, "alice", "different-pass")


def test_get_by_username_returns_user(users_table):
    created = users_svc.create_user(users_table, "bob", "passw0rd")
    found = users_svc.get_by_username(users_table, "bob")
    assert found is not None
    assert found.user_id == created.user_id
    assert found.username == "bob"


def test_get_by_username_returns_none_for_missing(users_table):
    assert users_svc.get_by_username(users_table, "nobody") is None


def test_authenticate_returns_user_on_success(users_table):
    users_svc.create_user(users_table, "carol", "rightpass")
    user = users_svc.authenticate(users_table, "carol", "rightpass")
    assert user is not None
    assert user.username == "carol"


def test_authenticate_returns_none_on_wrong_password(users_table):
    users_svc.create_user(users_table, "dave", "rightpass")
    assert users_svc.authenticate(users_table, "dave", "wrongpass") is None


def test_authenticate_returns_none_on_unknown_user(users_table):
    assert users_svc.authenticate(users_table, "ghost", "anypass") is None
