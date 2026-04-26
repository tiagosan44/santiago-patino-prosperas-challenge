"""SQS publisher.

Routing rule: report_type ∈ {audit, executive_summary} → high priority.
Everything else → standard. The rule is a simple set lookup so it's
cheap and easy to extend by configuration if needed later.
"""
import json
from datetime import UTC, datetime
from typing import Any

from ..core.config import get_settings
from ..models.job import JobPriority


HIGH_PRIORITY_REPORT_TYPES = frozenset({"audit", "executive_summary"})


def priority_for_report_type(report_type: str) -> JobPriority:
    return JobPriority.HIGH if report_type in HIGH_PRIORITY_REPORT_TYPES else JobPriority.STANDARD


def _get_queue_url(priority: JobPriority) -> str:
    """Resolves the queue URL for a given priority. Patched in tests."""
    settings = get_settings()
    return (
        settings.sqs_high_queue_url
        if priority == JobPriority.HIGH
        else settings.sqs_standard_queue_url
    )


def publish_job(
    sqs,
    *,
    job_id: str,
    user_id: str,
    report_type: str,
    priority: JobPriority,
    params: dict[str, Any],
    attempt: int = 1,
    version: int = 1,
) -> str:
    queue_url = _get_queue_url(priority)
    body = {
        "version": version,
        "job_id": job_id,
        "user_id": user_id,
        "report_type": report_type,
        "params": params,
        "enqueued_at": datetime.now(UTC).isoformat(),
        "attempt": attempt,
    }
    res = sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(body))
    return res["MessageId"]
