"""User domain model.

Pure Pydantic v2 model — no DynamoDB coupling. The service layer is
responsible for translating to/from DynamoDB items.
"""
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class User(BaseModel):
    user_id: str
    username: str
    password_hash: str
    created_at: str

    @classmethod
    def new(cls, username: str, password_hash: str) -> "User":
        return cls(
            user_id=str(uuid.uuid4()),
            username=username,
            password_hash=password_hash,
            created_at=datetime.now(UTC).isoformat(),
        )


class UserCredentials(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
