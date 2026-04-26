"""Jobs domain service.

Persistence layer for Job entities. Encapsulates:
- Cursor-based pagination (DynamoDB does not support OFFSET)
- Optimistic locking via the `version` attribute
- Idempotent status transitions (COMPLETED keeps result_url, FAILED keeps error)

Why optimistic locking: SQS visibility timeout can briefly let two
workers receive the same message. Optimistic locking ensures only the
first update lands; the loser retries and sees the new state.
"""
import base64
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from ..models.job import Job, JobPage, JobPriority, JobStatus


class OptimisticLockError(Exception):
    """Raised when an update's expected_version does not match what's stored."""


def _encode_cursor(last_evaluated_key: dict | None) -> str | None:
    if not last_evaluated_key:
        return None
    # Decimals appear in DynamoDB items; convert to int/float for JSON
    serializable = {
        k: (float(v) if isinstance(v, Decimal) else v) for k, v in last_evaluated_key.items()
    }
    raw = json.dumps(serializable, sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str | None) -> dict | None:
    if not cursor:
        return None
    raw = base64.urlsafe_b64decode(cursor.encode())
    return json.loads(raw)


def _item_to_job(item: dict) -> Job:
    """Coerce DynamoDB item (with Decimal for numbers) into a Job."""
    coerced = dict(item)
    coerced["version"] = int(coerced.get("version", 1))
    coerced["attempts"] = int(coerced.get("attempts", 0))
    return Job(**coerced)


def create_job(
    table,
    user_id: str,
    report_type: str,
    priority: JobPriority,
    params: dict[str, Any],
) -> Job:
    job = Job.new(user_id=user_id, report_type=report_type, priority=priority, params=params)
    item = job.model_dump(mode="json")  # enums -> strings
    table.put_item(Item=item, ConditionExpression="attribute_not_exists(job_id)")
    return job


def get_job(table, job_id: str) -> Job | None:
    res = table.get_item(Key={"job_id": job_id})
    item = res.get("Item")
    return _item_to_job(item) if item else None


def list_jobs_by_user(
    table, user_id: str, limit: int = 20, cursor: str | None = None
) -> JobPage:
    kwargs: dict[str, Any] = {
        "IndexName": "user-created-index",
        "KeyConditionExpression": Key("user_id").eq(user_id),
        "Limit": limit,
        "ScanIndexForward": False,  # newest first
    }
    last_key = _decode_cursor(cursor)
    if last_key:
        kwargs["ExclusiveStartKey"] = last_key

    res = table.query(**kwargs)
    items = [_item_to_job(it) for it in res.get("Items", [])]
    next_cursor = _encode_cursor(res.get("LastEvaluatedKey"))
    return JobPage(items=items, next_cursor=next_cursor)


def update_job_status(
    table,
    *,
    job_id: str,
    expected_version: int,
    status: JobStatus,
    result_url: str | None = None,
    error: str | None = None,
    increment_attempts: bool = False,
) -> Job:
    """Compare-and-swap update. Raises OptimisticLockError on version mismatch."""
    now = datetime.now(UTC).isoformat()
    set_parts = ["#st = :st", "updated_at = :now", "version = :next"]
    names = {"#st": "status"}
    values: dict[str, Any] = {
        ":st": status.value,
        ":now": now,
        ":expected": expected_version,
        ":next": expected_version + 1,
    }
    if result_url is not None:
        set_parts.append("result_url = :ru")
        values[":ru"] = result_url
    if error is not None:
        set_parts.append("#err = :err")
        names["#err"] = "error"
        values[":err"] = error

    add_parts = []
    if increment_attempts:
        add_parts.append("attempts :one")
        values[":one"] = 1

    update_expr = "SET " + ", ".join(set_parts)
    if add_parts:
        update_expr += " ADD " + ", ".join(add_parts)

    try:
        res = table.update_item(
            Key={"job_id": job_id},
            UpdateExpression=update_expr,
            ConditionExpression="version = :expected",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise OptimisticLockError(
                f"job {job_id} expected version {expected_version}, got different"
            ) from e
        raise
    return _item_to_job(res["Attributes"])
