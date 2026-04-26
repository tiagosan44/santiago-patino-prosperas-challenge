"""Dependency-aware health check.

Pings each downstream dep with a cheap operation and reports per-dep
status. Returns 200 if all deps are healthy, 503 otherwise.

Why per-dep status (not just 200/500): when on-call sees a 503 they
need to know WHICH dependency to look at. A flat 'unhealthy' wastes
time. The deps map gives them an immediate hint.

Each check has a short timeout. We never block the health endpoint
on a hung dep.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..core import aws as aws_factories
from ..core.config import get_settings
from ..core.logging_config import get_logger
from ..services import realtime

router = APIRouter(tags=["health"])
log = get_logger(__name__)


CHECK_TIMEOUT_SECONDS = 2.0


# ---------- per-dep checks ----------

def _check_dynamodb() -> None:
    """Raises on failure."""
    settings = get_settings()
    aws_factories.dynamo_resource().meta.client.describe_table(
        TableName=settings.dynamodb_jobs_table
    )


def _check_sqs(queue_url: str) -> None:
    aws_factories.sqs_client().get_queue_attributes(
        QueueUrl=queue_url, AttributeNames=["QueueArn"]
    )


def _check_s3() -> None:
    settings = get_settings()
    aws_factories.s3_client().head_bucket(Bucket=settings.s3_reports_bucket)


def _check_redis() -> None:
    client = realtime.get_redis_client()
    if not client.ping():
        raise RuntimeError("redis ping returned falsey")


# ---------- runner with per-check timeout ----------

def _run_with_timeout(fn, *args) -> str:
    """Returns 'healthy' on success, error string on failure."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        try:
            future = ex.submit(fn, *args)
            future.result(timeout=CHECK_TIMEOUT_SECONDS)
            return "healthy"
        except FutureTimeoutError:
            log.warning("health_check_timeout", check=fn.__name__)
            return "timeout"
        except Exception as e:  # noqa: BLE001
            log.warning("health_check_failed", check=fn.__name__, error=str(e))
            return f"unhealthy: {type(e).__name__}"


# ---------- endpoint ----------

@router.get("/health")
async def health() -> JSONResponse:
    settings = get_settings()
    deps = {
        "dynamodb": _run_with_timeout(_check_dynamodb),
        "sqs_high": _run_with_timeout(_check_sqs, settings.sqs_high_queue_url),
        "sqs_standard": _run_with_timeout(_check_sqs, settings.sqs_standard_queue_url),
        "sqs_dlq": _run_with_timeout(_check_sqs, settings.sqs_dlq_url),
        "s3": _run_with_timeout(_check_s3),
        "redis": _run_with_timeout(_check_redis),
    }

    all_healthy = all(v == "healthy" for v in deps.values())
    body = {
        "status": "healthy" if all_healthy else "unhealthy",
        "deps": deps,
        "version": settings.git_sha,
    }
    status_code = 200 if all_healthy else 503
    return JSONResponse(content=body, status_code=status_code)
