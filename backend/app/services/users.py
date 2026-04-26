"""User domain service: create, lookup, authenticate.

Uses bcrypt directly for password hashing (bypasses passlib which is
incompatible with bcrypt >= 4.x). Lookups by username go through the
`username-index` GSI on the users table.
"""
import bcrypt
from botocore.exceptions import ClientError

from ..models.user import User

# A pre-computed dummy hash used to keep authenticate() constant-time
# even when the username does not exist.  Generated once at import time.
_DUMMY_HASH: bytes = bcrypt.hashpw(b"__dummy__", bcrypt.gensalt())


class UsernameAlreadyExistsError(Exception):
    """Raised when attempting to create a user whose username is taken."""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_user(table, username: str, password: str) -> User:
    """Persist a new user. Raises UsernameAlreadyExistsError on conflict.

    Two-step check is intentional: GSI is eventually consistent, but
    the conditional put on the primary key prevents id collisions.
    Username uniqueness is enforced via the GSI lookup; for stronger
    guarantees in production you would use a separate lookup item
    pattern in DynamoDB. For this challenge GSI is sufficient.
    """
    if get_by_username(table, username) is not None:
        raise UsernameAlreadyExistsError(username)
    user = User.new(username, hash_password(password))
    try:
        table.put_item(
            Item=user.model_dump(),
            ConditionExpression="attribute_not_exists(user_id)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Extremely unlikely UUID collision — surface as duplicate
            raise UsernameAlreadyExistsError(username) from e
        raise
    return user


def get_by_username(table, username: str) -> User | None:
    """Lookup via username-index GSI."""
    res = table.query(
        IndexName="username-index",
        KeyConditionExpression="username = :u",
        ExpressionAttributeValues={":u": username},
        Limit=1,
    )
    items = res.get("Items", [])
    return User(**items[0]) if items else None


def authenticate(table, username: str, password: str) -> User | None:
    """Returns the user on success, None on any failure (no enumeration leak)."""
    user = get_by_username(table, username)
    if user is None:
        # Verify against a dummy hash to keep timing constant — prevents an
        # attacker from distinguishing "user exists" from "user doesn't exist"
        # via response-time analysis.  bcrypt is intentionally slow.
        bcrypt.checkpw(password.encode(), _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
