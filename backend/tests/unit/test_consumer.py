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
def sns_topic(aws):
    sns = boto3.client("sns", region_name="us-east-1")
    arn = sns.create_topic(Name="job-updates")["TopicArn"]
    return {"client": sns, "arn": arn}


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


def test_handle_message_happy_path_completes_job(jobs_table, s3_bucket, sns_topic):
    job_id = _create_pending_job(jobs_table)
    msg = _build_message(job_id)

    with patch("worker.processor.simulate_sleep"):
        ack = consumer.handle_message(
            msg,
            jobs_table=jobs_table,
            s3=s3_bucket,
            sns=sns_topic["client"],
            bucket="prosperas-reports-test",
            topic_arn=sns_topic["arn"],
        )

    assert ack is True
    job = jobs_svc.get_job(jobs_table, job_id)
    assert job.status == JobStatus.COMPLETED
    assert job.result_url == f"reports/u-1/{job_id}/result.json"
    assert job.attempts == 1
    assert job.version == 3  # PENDING(1) -> PROCESSING(2) -> COMPLETED(3)


def test_handle_message_processing_error_marks_failed(jobs_table, s3_bucket, sns_topic):
    job_id = _create_pending_job(jobs_table, report_type="force_failure")
    msg = _build_message(job_id, report_type="force_failure")

    with patch("worker.processor.simulate_sleep"):
        ack = consumer.handle_message(
            msg,
            jobs_table=jobs_table,
            s3=s3_bucket,
            sns=sns_topic["client"],
            bucket="prosperas-reports-test",
            topic_arn=sns_topic["arn"],
        )

    assert ack is True
    job = jobs_svc.get_job(jobs_table, job_id)
    assert job.status == JobStatus.FAILED
    assert "force_failure" in (job.error or "")


def test_handle_message_duplicate_completed_job_acks(jobs_table, s3_bucket, sns_topic):
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
            sns=sns_topic["client"],
            bucket="prosperas-reports-test",
            topic_arn=sns_topic["arn"],
        )

    assert ack is True
    # Processor was NOT called for the duplicate
    mock_sleep.assert_not_called()


def test_handle_message_optimistic_lock_collision_acks(jobs_table, s3_bucket, sns_topic):
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
            sns=sns_topic["client"],
            bucket="prosperas-reports-test",
            topic_arn=sns_topic["arn"],
        )

    assert ack is True
    mock_sleep.assert_not_called()


def test_handle_message_publishes_sns_event_on_completion(jobs_table, s3_bucket, sns_topic):
    """SNS publish was called once with the COMPLETED event."""
    job_id = _create_pending_job(jobs_table)
    msg = _build_message(job_id)

    sns_spy = MagicMock(wraps=sns_topic["client"])

    with patch("worker.processor.simulate_sleep"):
        consumer.handle_message(
            msg,
            jobs_table=jobs_table,
            s3=s3_bucket,
            sns=sns_spy,
            bucket="prosperas-reports-test",
            topic_arn=sns_topic["arn"],
        )

    assert sns_spy.publish.called
    call = sns_spy.publish.call_args
    assert call.kwargs["TopicArn"] == sns_topic["arn"]
    body = json.loads(call.kwargs["Message"])
    assert body["job_id"] == job_id
    assert body["status"] == "COMPLETED"
    assert body["user_id"] == "u-1"
    assert body["result_url"] == f"reports/u-1/{job_id}/result.json"


def test_handle_message_publishes_sns_event_on_failure(jobs_table, s3_bucket, sns_topic):
    job_id = _create_pending_job(jobs_table, report_type="force_failure")
    msg = _build_message(job_id, report_type="force_failure")

    sns_spy = MagicMock(wraps=sns_topic["client"])

    with patch("worker.processor.simulate_sleep"):
        consumer.handle_message(
            msg,
            jobs_table=jobs_table,
            s3=s3_bucket,
            sns=sns_spy,
            bucket="prosperas-reports-test",
            topic_arn=sns_topic["arn"],
        )

    body = json.loads(sns_spy.publish.call_args.kwargs["Message"])
    assert body["status"] == "FAILED"


def test_handle_message_returns_false_on_unparseable_body(jobs_table, s3_bucket, sns_topic):
    """Corrupt body -> let SQS retry (which will eventually DLQ)."""
    msg = {
        "MessageId": "m-1",
        "ReceiptHandle": "rh-1",
        "Body": "not-json",
        "Attributes": {"ApproximateReceiveCount": "1"},
    }
    ack = consumer.handle_message(
        msg, jobs_table=jobs_table, s3=s3_bucket,
        sns=sns_topic["client"], bucket="prosperas-reports-test",
        topic_arn=sns_topic["arn"],
    )
    assert ack is False


def test_handle_message_missing_job_acks(jobs_table, s3_bucket, sns_topic):
    """If the message references a non-existent job, ack and move on (poison)."""
    msg = _build_message("non-existent-job-id")

    with patch("worker.processor.simulate_sleep") as mock_sleep:
        ack = consumer.handle_message(
            msg, jobs_table=jobs_table, s3=s3_bucket,
            sns=sns_topic["client"], bucket="prosperas-reports-test",
            topic_arn=sns_topic["arn"],
        )
    assert ack is True
    mock_sleep.assert_not_called()
