"""Unit tests for the metrics emitter.

Uses moto's mock_cloudwatch via the shared `aws` fixture; we read
back the metrics from CloudWatch's mock store to verify they were
emitted with correct dimensions.
"""
import boto3
import pytest

from app.core import metrics, aws as aws_factories


@pytest.fixture
def cw(aws):
    aws_factories.reset_clients()
    return boto3.client("cloudwatch", region_name="us-east-1")


def _list_metrics(cw, *, name):
    res = cw.list_metrics(Namespace="Prosperas", MetricName=name)
    return res.get("Metrics", [])


def test_job_created_records_metric_with_dimensions(cw):
    metrics.job_created(report_type="sales", priority="standard")
    found = _list_metrics(cw, name="jobs.created")
    assert len(found) == 1
    dims = {d["Name"]: d["Value"] for d in found[0]["Dimensions"]}
    assert dims == {"report_type": "sales", "priority": "standard"}


def test_job_completed_records_metric(cw):
    metrics.job_completed(report_type="audit", priority="high")
    assert _list_metrics(cw, name="jobs.completed")


def test_job_failed_records_metric_with_error_type(cw):
    metrics.job_failed(report_type="sales", error_type="TimeoutError")
    found = _list_metrics(cw, name="jobs.failed")
    assert len(found) == 1
    dims = {d["Name"]: d["Value"] for d in found[0]["Dimensions"]}
    assert dims == {"report_type": "sales", "error_type": "TimeoutError"}


def test_job_processing_duration_records_metric(cw):
    metrics.job_processing_duration_seconds(report_type="sales", seconds=12.5)
    assert _list_metrics(cw, name="jobs.processing_duration_seconds")


def test_metrics_are_failure_tolerant(monkeypatch):
    """If CloudWatch raises, metrics module must NOT propagate."""
    class FailClient:
        def put_metric_data(self, **kwargs):
            raise RuntimeError("simulated cloudwatch outage")

    monkeypatch.setattr(metrics, "cloudwatch_client", lambda: FailClient())

    # These calls must NOT raise
    metrics.job_created(report_type="sales", priority="standard")
    metrics.job_completed(report_type="sales", priority="standard")
    metrics.job_failed(report_type="sales")
    metrics.job_processing_duration_seconds(report_type="sales", seconds=1)
