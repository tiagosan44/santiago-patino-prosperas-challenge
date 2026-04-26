"""CloudWatch custom metrics emitter.

Wraps boto3.cloudwatch.put_metric_data with two design choices:

1. Failure-tolerant: if CloudWatch is unreachable (network blip, IAM
   issue), the metric call MUST NOT raise — observability never blocks
   business logic. Errors are logged and swallowed.

2. Dimensional: every counter accepts a dict of dimensions so we can
   slice in CloudWatch by report_type, priority, error_type, etc.
"""
from typing import Any

from .aws import cloudwatch_client
from .logging_config import get_logger

NAMESPACE = "Prosperas"
log = get_logger(__name__)


def _put_metric(
    *,
    name: str,
    value: float,
    unit: str = "Count",
    dimensions: dict[str, str] | None = None,
) -> None:
    """Best-effort put_metric_data; never raises."""
    metric: dict[str, Any] = {
        "MetricName": name,
        "Value": value,
        "Unit": unit,
    }
    if dimensions:
        metric["Dimensions"] = [{"Name": k, "Value": v} for k, v in dimensions.items()]

    try:
        cloudwatch_client().put_metric_data(
            Namespace=NAMESPACE,
            MetricData=[metric],
        )
    except Exception as e:  # noqa: BLE001
        # Observability must never break a business path
        log.warning("cloudwatch_put_metric_failed", metric=name, error=str(e))


def job_created(report_type: str, priority: str) -> None:
    _put_metric(
        name="jobs.created",
        value=1,
        dimensions={"report_type": report_type, "priority": priority},
    )


def job_completed(report_type: str, priority: str) -> None:
    _put_metric(
        name="jobs.completed",
        value=1,
        dimensions={"report_type": report_type, "priority": priority},
    )


def job_failed(report_type: str, error_type: str = "ProcessingError") -> None:
    _put_metric(
        name="jobs.failed",
        value=1,
        dimensions={"report_type": report_type, "error_type": error_type},
    )


def job_processing_duration_seconds(report_type: str, seconds: float) -> None:
    _put_metric(
        name="jobs.processing_duration_seconds",
        value=seconds,
        unit="Seconds",
        dimensions={"report_type": report_type},
    )
