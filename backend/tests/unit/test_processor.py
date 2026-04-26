"""Unit tests for worker.processor.

The processor is intentionally synchronous and pure-function-shaped:
input = job descriptor + s3 client. Output = S3 key. Side effect = an
S3 object at that key. The simulate_sleep is patchable so tests run
in milliseconds.
"""
import json
from unittest.mock import patch

import boto3
import pytest

from worker import processor


@pytest.fixture
def s3_bucket(aws):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="prosperas-reports-test")
    return s3


# ---- generate_dummy_data ----

def test_generate_dummy_data_returns_dict_with_metadata():
    data = processor.generate_dummy_data(report_type="sales", params={"format": "json"})
    assert isinstance(data, dict)
    assert data["report_type"] == "sales"
    assert "generated_at" in data
    assert "rows" in data and isinstance(data["rows"], list)
    # Some rows present (deterministic shape)
    assert len(data["rows"]) > 0


def test_generate_dummy_data_varies_by_report_type():
    sales = processor.generate_dummy_data(report_type="sales", params={})
    inventory = processor.generate_dummy_data(report_type="inventory", params={})
    assert sales["report_type"] != inventory["report_type"]


# ---- simulate_sleep ----

def test_simulate_sleep_uses_random_within_bounds():
    """Confirm bounds; we patch random.uniform to verify the call."""
    with patch("worker.processor.random.uniform", return_value=7.0) as mock_uniform, \
         patch("worker.processor.time.sleep") as mock_sleep:
        processor.simulate_sleep()
        mock_uniform.assert_called_once_with(5.0, 30.0)
        mock_sleep.assert_called_once_with(7.0)


# ---- process_job ----

def test_process_job_uploads_to_correct_s3_key(s3_bucket):
    with patch("worker.processor.simulate_sleep"):
        key = processor.process_job(
            s3=s3_bucket,
            bucket="prosperas-reports-test",
            user_id="u-123",
            job_id="job-abc",
            report_type="sales",
            params={"format": "json"},
        )
    assert key == "reports/u-123/job-abc/result.json"

    obj = s3_bucket.get_object(Bucket="prosperas-reports-test", Key=key)
    body = json.loads(obj["Body"].read())
    assert body["report_type"] == "sales"


def test_process_job_returns_key_only_not_url(s3_bucket):
    """Defensive: never return a presigned URL or full HTTP URL — keep it stable."""
    with patch("worker.processor.simulate_sleep"):
        key = processor.process_job(
            s3=s3_bucket,
            bucket="prosperas-reports-test",
            user_id="u-1",
            job_id="j-1",
            report_type="sales",
            params={},
        )
    assert not key.startswith("http")
    assert key.startswith("reports/")


def test_process_job_calls_simulate_sleep(s3_bucket):
    with patch("worker.processor.simulate_sleep") as mock_sleep:
        processor.process_job(
            s3=s3_bucket,
            bucket="prosperas-reports-test",
            user_id="u-1",
            job_id="j-1",
            report_type="sales",
            params={},
        )
    mock_sleep.assert_called_once()


# ---- ProcessingError ----

def test_force_failure_report_type_raises_processing_error(s3_bucket):
    """report_type='force_failure' is a test hook — used by integration tests
    and by the frontend to demonstrate FAILED state."""
    with patch("worker.processor.simulate_sleep"), \
         pytest.raises(processor.ProcessingError):
        processor.process_job(
            s3=s3_bucket,
            bucket="prosperas-reports-test",
            user_id="u-1",
            job_id="j-1",
            report_type="force_failure",
            params={},
        )
