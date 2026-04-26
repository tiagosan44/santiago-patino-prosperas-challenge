"""Job domain model.

Pure Pydantic v2. The service layer translates to/from DynamoDB items
(handles Decimal/int conversion for the version field).
"""
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class JobPriority(str, Enum):
    HIGH = "high"
    STANDARD = "standard"


class Job(BaseModel):
    job_id: str
    user_id: str
    status: JobStatus
    report_type: str
    priority: JobPriority
    params: dict[str, Any] = Field(default_factory=dict)
    result_url: str | None = None
    error: str | None = None
    attempts: int = 0
    created_at: str
    updated_at: str
    version: int = 1

    @classmethod
    def new(
        cls,
        user_id: str,
        report_type: str,
        priority: JobPriority,
        params: dict[str, Any],
    ) -> "Job":
        now = datetime.now(UTC).isoformat()
        return cls(
            job_id=str(uuid.uuid4()),
            user_id=user_id,
            status=JobStatus.PENDING,
            report_type=report_type,
            priority=priority,
            params=params,
            created_at=now,
            updated_at=now,
            version=1,
            attempts=0,
        )


class JobCreateRequest(BaseModel):
    """Payload for POST /jobs."""
    report_type: str = Field(min_length=1, max_length=64)
    date_range: str | None = None
    format: str = Field(default="json", pattern="^(json|csv|pdf)$")


class JobPage(BaseModel):
    items: list[Job]
    next_cursor: str | None = None
