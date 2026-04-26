"""Unit tests for the SQS consumer (sync version).

The consumer is synchronous in this task; the async upgrade lands in
Task 3.3 with aioboto3 and asyncio.gather concurrency.
"""
import json
from unittest.mock import patch, MagicMock

import boto3
import pytest

from app.models.job import JobPriority, JobStatus
from app.services import jobs as jobs_svc
from worker import consumer, processor


@pytest.fixture
def cw_client(aws):
    """Activates moto's cloudwatch mock and resets the cached client."""
    from app.core import aws as aws_factories
    aws_factories.reset_clients()
    return boto3.client("cloudwatch", region_name="us-east-1")


# ---- Fixtures ----

@pytest.fixture
def sqs_queues(aws):
    sqs = boto3.client("sqs", region_name="us-east-1")
    high = sqs.create_queue(QueueName="jobs-high")["QueueUrl"]
    standard = sqs.create_queue(QueueName="jobs-standard")["QueueUrl"]
    sqs.create_queue(QueueName="jobs-dlq")
    return {"high": high, "standard": standard, "client": sqs}


@pytest.fixture
def s3_bucket(aws):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="prosperas-reports-test")
    return s3


@pytest.fixture
def redis_client():
    import fakeredis
    return fakeredis.FakeStrictRedis(decode_responses=True)


# ---- poll_next_message ----

def test_poll_next_message_prefers_high_queue(sqs_queues, monkeypatch):
    monkeypatch.setattr(consumer, "_high_queue_url", lambda: sqs_queues["high"])
    monkeypatch.setattr(consumer, "_standard_queue_url", lambda: sqs_queues["standard"])

    sqs_queues["client"].send_message(QueueUrl=sqs_queues["high"], MessageBody='{"job_id":"H"}')
    sqs_queues["client"].send_message(QueueUrl=sqs_queues["standard"], MessageBody='{"job_id":"S"}')

    msg = consumer.poll_next_message(sqs_queues["client"], wait_high=0, wait_standard=0)
    assert msg is not None
    assert json.loads(msg["Body"])["job_id"] == "H"


def test_poll_next_message_falls_back_to_standard(sqs_queues, monkeypatch):
    monkeypatch.setattr(consumer, "_high_queue_url", lambda: sqs_queues["high"])
    monkeypatch.setattr(consumer, "_standard_queue_url", lambda: sqs_queues["standard"])

    sqs_queues["client"].send_message(QueueUrl=sqs_queues["standard"], MessageBody='{"job_id":"S"}')

    msg = consumer.poll_next_message(sqs_queues["client"], wait_high=0, wait_standard=0)
    assert msg is not None
    assert json.loads(msg["Body"])["job_id"] == "S"


def test_poll_next_message_returns_none_when_both_empty(sqs_queues, monkeypatch):
    monkeypatch.setattr(consumer, "_high_queue_url", lambda: sqs_queues["high"])
    monkeypatch.setattr(consumer, "_standard_queue_url", lambda: sqs_queues["standard"])

    msg = consumer.poll_next_message(sqs_queues["client"], wait_high=0, wait_standard=0)
    assert msg is None


# ---- handle_message ----

def _create_pending_job(jobs_table, user_id="u-1", report_type="sales") -> str:
    """Helper: create a PENDING job, return job_id."""
    job = jobs_svc.create_job(
        jobs_table, user_id=user_id, report_type=report_type,
        priority=JobPriority.STANDARD, params={"format": "json"},
    )
    return job.job_id


def _build_message(job_id: str, user_id="u-1", report_type="sales") -> dict:
    return {
        "MessageId": "m-1",
        "ReceiptHandle": "rh-1",
        "Body": json.dumps({
            "version": 1,
            "job_id": job_id,
            "user_id": user_id,
            "report_type": report_type,
            "params": {"format": "json"},
            "enqueued_at": "2026-04-26T12:00:00+00:00",
            "attempt": 1,
        }),
        "Attributes": {"ApproximateReceiveCount": "1"},
    }


def test_handle_message_happy_path_completes_job(jobs_table, s3_bucket, redis_client):
    job_id = _create_pending_job(jobs_table)
    msg = _build_message(job_id)

    with patch("worker.processor.simulate_sleep"):
        ack = consumer.handle_message(
            msg,
            jobs_table=jobs_table,
            s3=s3_bucket,
            redis_client=redis_client,
            bucket="prosperas-reports-test",
            sqs=MagicMock(),
            queue_url="http://x",
        )

    assert ack is True
    job = jobs_svc.get_job(jobs_table, job_id)
    assert job.status == JobStatus.COMPLETED
    assert job.result_url == f"reports/u-1/{job_id}/result.json"
    assert job.attempts == 1
    assert job.version == 3  # PENDING(1) -> PROCESSING(2) -> COMPLETED(3)


def test_handle_message_processing_error_marks_failed(jobs_table, s3_bucket, redis_client):
    job_id = _create_pending_job(jobs_table, report_type="force_failure")
    msg = _build_message(job_id, report_type="force_failure")
    msg["Attributes"]["ApproximateReceiveCount"] = "3"  # final attempt

    sqs_mock = MagicMock()

    with patch("worker.processor.simulate_sleep"):
        ack = consumer.handle_message(
            msg,
            jobs_table=jobs_table,
            s3=s3_bucket,
            redis_client=redis_client,
            bucket="prosperas-reports-test",
            sqs=sqs_mock,
            queue_url="http://sqs/test",
        )

    assert ack is True
    job = jobs_svc.get_job(jobs_table, job_id)
    assert job.status == JobStatus.FAILED
    assert "force_failure" in (job.error or "")


def test_handle_message_duplicate_completed_job_acks(jobs_table, s3_bucket, redis_client):
    """If the job is already COMPLETED, the message is a duplicate; ack and skip."""
    job_id = _create_pending_job(jobs_table)
    # Mark it completed
    jobs_svc.update_job_status(
        jobs_table, job_id=job_id, expected_version=1,
        status=JobStatus.COMPLETED, result_url="reports/u-1/j/result.json",
    )
    msg = _build_message(job_id)

    with patch("worker.processor.simulate_sleep") as mock_sleep:
        ack = consumer.handle_message(
            msg,
            jobs_table=jobs_table,
            s3=s3_bucket,
            redis_client=redis_client,
            bucket="prosperas-reports-test",
            sqs=MagicMock(),
            queue_url="http://x",
        )

    assert ack is True
    # Processor was NOT called for the duplicate
    mock_sleep.assert_not_called()


def test_handle_message_optimistic_lock_collision_acks(jobs_table, s3_bucket, redis_client):
    """If another worker won the race, our update fails; we ack the duplicate."""
    job_id = _create_pending_job(jobs_table)
    # Simulate another worker grabbing the job: bump version directly
    jobs_svc.update_job_status(
        jobs_table, job_id=job_id, expected_version=1,
        status=JobStatus.PROCESSING, increment_attempts=True,
    )
    # Now our handler will read version=2, then try update from version=2.
    # That actually should succeed (no collision in this test). To force
    # a collision, mock get_job to return version=1 stale.
    real_get_job = jobs_svc.get_job

    def stale_get_job(table, jid):
        job = real_get_job(table, jid)
        if job is None:
            return None
        # Return a clone with the stale version=1
        return type(job)(**{**job.model_dump(), "version": 1, "status": JobStatus.PENDING})

    msg = _build_message(job_id)

    with patch("worker.consumer.jobs_svc.get_job", side_effect=stale_get_job), \
         patch("worker.processor.simulate_sleep") as mock_sleep:
        ack = consumer.handle_message(
            msg,
            jobs_table=jobs_table,
            s3=s3_bucket,
            redis_client=redis_client,
            bucket="prosperas-reports-test",
            sqs=MagicMock(),
            queue_url="http://x",
        )

    assert ack is True
    mock_sleep.assert_not_called()


def test_handle_message_publishes_redis_event_on_completion(jobs_table, s3_bucket, redis_client):
    """Redis publish was called once with the COMPLETED event."""
    job_id = _create_pending_job(jobs_table)
    msg = _build_message(job_id)

    pubsub = redis_client.pubsub()
    pubsub.subscribe("job-updates")
    pubsub.get_message(timeout=1)  # drain subscribe-confirmation

    with patch("worker.processor.simulate_sleep"):
        consumer.handle_message(
            msg,
            jobs_table=jobs_table,
            s3=s3_bucket,
            redis_client=redis_client,
            bucket="prosperas-reports-test",
            sqs=MagicMock(),
            queue_url="http://x",
        )

    msg = pubsub.get_message(timeout=2)
    assert msg is not None
    body = json.loads(msg["data"])
    assert body["job_id"] == job_id
    assert body["status"] == "COMPLETED"
    assert body["user_id"] == "u-1"
    assert body["result_url"] == f"reports/u-1/{job_id}/result.json"


def test_handle_message_publishes_redis_event_on_failure(jobs_table, s3_bucket, redis_client):
    job_id = _create_pending_job(jobs_table, report_type="force_failure")
    msg = _build_message(job_id, report_type="force_failure")
    msg["Attributes"]["ApproximateReceiveCount"] = "3"  # final attempt -> FAILED

    pubsub = redis_client.pubsub()
    pubsub.subscribe("job-updates")
    pubsub.get_message(timeout=1)  # drain subscribe-confirmation

    sqs_mock = MagicMock()

    with patch("worker.processor.simulate_sleep"):
        consumer.handle_message(
            msg,
            jobs_table=jobs_table,
            s3=s3_bucket,
            redis_client=redis_client,
            bucket="prosperas-reports-test",
            sqs=sqs_mock,
            queue_url="http://x",
        )

    msg = pubsub.get_message(timeout=2)
    assert msg is not None
    body = json.loads(msg["data"])
    assert body["status"] == "FAILED"


def test_handle_message_returns_false_on_unparseable_body(jobs_table, s3_bucket, redis_client):
    """Corrupt body -> let SQS retry (which will eventually DLQ)."""
    msg = {
        "MessageId": "m-1",
        "ReceiptHandle": "rh-1",
        "Body": "not-json",
        "Attributes": {"ApproximateReceiveCount": "1"},
    }
    ack = consumer.handle_message(
        msg, jobs_table=jobs_table, s3=s3_bucket,
        redis_client=redis_client, bucket="prosperas-reports-test",
        sqs=MagicMock(), queue_url="http://x",
    )
    assert ack is False


def test_handle_message_missing_job_acks(jobs_table, s3_bucket, redis_client):
    """If the message references a non-existent job, ack and move on (poison)."""
    msg = _build_message("non-existent-job-id")

    with patch("worker.processor.simulate_sleep") as mock_sleep:
        ack = consumer.handle_message(
            msg, jobs_table=jobs_table, s3=s3_bucket,
            redis_client=redis_client, bucket="prosperas-reports-test",
            sqs=MagicMock(), queue_url="http://x",
        )
    assert ack is True
    mock_sleep.assert_not_called()


def test_handle_message_emits_completed_metric(jobs_table, s3_bucket, redis_client, cw_client):
    job_id = _create_pending_job(jobs_table)
    msg = _build_message(job_id)

    with patch("worker.processor.simulate_sleep"):
        consumer.handle_message(
            msg,
            jobs_table=jobs_table,
            s3=s3_bucket,
            redis_client=redis_client,
            bucket="prosperas-reports-test",
            sqs=MagicMock(),
            queue_url="http://x",
        )

    res = cw_client.list_metrics(Namespace="Prosperas", MetricName="jobs.completed")
    assert len(res["Metrics"]) >= 1


def test_handle_message_emits_failed_metric(jobs_table, s3_bucket, redis_client, cw_client):
    job_id = _create_pending_job(jobs_table, report_type="force_failure")
    msg = _build_message(job_id, report_type="force_failure")
    msg["Attributes"]["ApproximateReceiveCount"] = "3"  # final attempt -> FAILED

    sqs_mock = MagicMock()

    with patch("worker.processor.simulate_sleep"):
        consumer.handle_message(
            msg,
            jobs_table=jobs_table,
            s3=s3_bucket,
            redis_client=redis_client,
            bucket="prosperas-reports-test",
            sqs=sqs_mock,
            queue_url="http://x",
        )

    res = cw_client.list_metrics(Namespace="Prosperas", MetricName="jobs.failed")
    assert len(res["Metrics"]) >= 1


# ---- back-off (B4) ----

def test_handle_message_first_failure_calls_change_visibility_with_90s(jobs_table, s3_bucket, redis_client):
    """First retry: visibility = 90s. Message NOT deleted (returns False)."""
    job_id = _create_pending_job(jobs_table, report_type="force_failure")
    msg = _build_message(job_id, report_type="force_failure")
    msg["Attributes"]["ApproximateReceiveCount"] = "1"  # first try

    sqs_mock = MagicMock()

    with patch("worker.processor.simulate_sleep"):
        ack = consumer.handle_message(
            msg,
            jobs_table=jobs_table,
            s3=s3_bucket,
            redis_client=redis_client,
            bucket="prosperas-reports-test",
            sqs=sqs_mock,
            queue_url="http://sqs/test-queue",
        )

    assert ack is False  # don't delete
    sqs_mock.change_message_visibility.assert_called_once()
    kwargs = sqs_mock.change_message_visibility.call_args.kwargs
    assert kwargs["VisibilityTimeout"] == 90
    assert kwargs["QueueUrl"] == "http://sqs/test-queue"
    assert kwargs["ReceiptHandle"] == "rh-1"

    # Job remains in PROCESSING (not FAILED) after retry
    job = jobs_svc.get_job(jobs_table, job_id)
    assert job.status == JobStatus.PROCESSING


def test_handle_message_second_failure_doubles_visibility_to_180s(jobs_table, s3_bucket, redis_client):
    job_id = _create_pending_job(jobs_table, report_type="force_failure")
    msg = _build_message(job_id, report_type="force_failure")
    msg["Attributes"]["ApproximateReceiveCount"] = "2"

    sqs_mock = MagicMock()

    with patch("worker.processor.simulate_sleep"):
        ack = consumer.handle_message(
            msg, jobs_table=jobs_table, s3=s3_bucket,
            redis_client=redis_client, bucket="prosperas-reports-test",
            sqs=sqs_mock, queue_url="http://sqs/q",
        )

    assert ack is False
    assert sqs_mock.change_message_visibility.call_args.kwargs["VisibilityTimeout"] == 180


def test_handle_message_third_failure_marks_failed_and_acks(jobs_table, s3_bucket, redis_client):
    """receive_count == 3: this IS the final allowed attempt. Mark FAILED, ack."""
    job_id = _create_pending_job(jobs_table, report_type="force_failure")
    msg = _build_message(job_id, report_type="force_failure")
    msg["Attributes"]["ApproximateReceiveCount"] = "3"

    sqs_mock = MagicMock()

    with patch("worker.processor.simulate_sleep"):
        ack = consumer.handle_message(
            msg, jobs_table=jobs_table, s3=s3_bucket,
            redis_client=redis_client, bucket="prosperas-reports-test",
            sqs=sqs_mock, queue_url="http://sqs/q",
        )

    assert ack is True
    sqs_mock.change_message_visibility.assert_not_called()

    job = jobs_svc.get_job(jobs_table, job_id)
    assert job.status == JobStatus.FAILED
    assert job.error is not None


def test_back_off_caps_at_900_seconds(jobs_table, s3_bucket, redis_client):
    """If somehow receive_count is very large but < 3, the cap is 900s."""
    # This test just exercises the math — at receive_count=2, value is 180s.
    # 90 * 2 ** (n-1) hits 900 at n=4, but we already mark FAILED at n=3.
    # So this test just validates the helper directly.
    from worker.consumer import _backoff_seconds
    assert _backoff_seconds(1) == 90
    assert _backoff_seconds(2) == 180
    assert _backoff_seconds(3) == 360  # we never call this in practice but verify formula
    assert _backoff_seconds(10) == 900  # capped


# ---- circuit breaker integration (B2) ----

def test_handle_message_skips_when_breaker_open(jobs_table, s3_bucket, redis_client):
    """If the breaker for this report_type is OPEN, message is left in SQS."""
    from worker import circuit_breaker as cb_module

    job_id = _create_pending_job(jobs_table)
    msg = _build_message(job_id)

    # Trip the breaker for "sales"
    for _ in range(3):
        cb_module.record_failure(redis_client, "sales")
    assert cb_module.allow(redis_client, "sales") is False

    sqs_mock = MagicMock()

    with patch("worker.processor.simulate_sleep") as mock_sleep:
        ack = consumer.handle_message(
            msg, jobs_table=jobs_table, s3=s3_bucket,
            redis_client=redis_client, bucket="prosperas-reports-test",
            sqs=sqs_mock, queue_url="http://x",
        )

    assert ack is False  # don't delete
    mock_sleep.assert_not_called()  # processor was NOT invoked
    sqs_mock.change_message_visibility.assert_called_once()


def test_successful_handle_records_success_to_breaker(jobs_table, s3_bucket, redis_client):
    from worker import circuit_breaker as cb_module
    job_id = _create_pending_job(jobs_table)
    msg = _build_message(job_id)

    # Pre-load some failures (below threshold)
    cb_module.record_failure(redis_client, "sales")
    cb_module.record_failure(redis_client, "sales")

    with patch("worker.processor.simulate_sleep"):
        consumer.handle_message(
            msg, jobs_table=jobs_table, s3=s3_bucket,
            redis_client=redis_client, bucket="prosperas-reports-test",
            sqs=MagicMock(), queue_url="http://x",
        )

    # Success should have reset failure_count
    state = redis_client.hgetall("circuit_breakers:sales")
    assert state.get("failure_count") == "0"


def test_third_consecutive_processing_error_opens_breaker(jobs_table, s3_bucket, redis_client):
    """3 PROCESSING-time failures (different jobs, same report_type) open breaker."""
    from worker import circuit_breaker as cb_module

    sqs_mock = MagicMock()

    for i in range(3):
        job_id = _create_pending_job(jobs_table, report_type="force_failure")
        msg = _build_message(job_id, report_type="force_failure")
        msg["Attributes"]["ApproximateReceiveCount"] = "1"  # so it doesn't mark FAILED yet

        with patch("worker.processor.simulate_sleep"):
            consumer.handle_message(
                msg, jobs_table=jobs_table, s3=s3_bucket,
                redis_client=redis_client, bucket="prosperas-reports-test",
                sqs=sqs_mock, queue_url="http://x",
            )

    # After 3 record_failure, the breaker for force_failure is OPEN
    assert cb_module.allow(redis_client, "force_failure") is False
