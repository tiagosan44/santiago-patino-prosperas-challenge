"""Critical scenario: a poison message that fails 3 times must end up in DLQ.

The flow:
  1. Producer enqueues a 'force_failure' job.
  2. Worker receives it (ApproximateReceiveCount=1) -> ProcessingError ->
     visibility extended (90s back-off). Message returns to queue.
  3. Worker receives it (ApproximateReceiveCount=2) -> 180s back-off.
  4. Worker receives it (ApproximateReceiveCount=3) -> handle_message
     marks job FAILED in DynamoDB and acks the message.

Because we mark FAILED at attempt 3 and ack, the message does not
actually reach SQS DLQ in our flow (we replaced the redrive with our
own 'mark FAILED + delete' on the final attempt). The DLQ is the
safety net for messages we haven't seen — for example, ones whose
body fails parsing on every attempt and returns False without acking.

This test exercises both:
  A) The normal poison-pill flow: 3 attempts, FAILED in DynamoDB.
  B) The corrupt-body flow: handler returns False every time; SQS
     redrives to DLQ on its own after maxReceiveCount=3.
"""
import json
from unittest.mock import MagicMock, patch

import boto3
import fakeredis
import pytest

from app.models.job import JobStatus
from app.services import jobs as jobs_svc
from worker import consumer


@pytest.fixture
def redis_client():
    return fakeredis.FakeStrictRedis(decode_responses=True)


@pytest.fixture
def s3_bucket(aws):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="prosperas-reports-test")
    return s3


def _build_message(job_id, *, user_id="u-1", report_type="force_failure", attempt=1):
    return {
        "MessageId": f"m-{attempt}",
        "ReceiptHandle": f"rh-{attempt}",
        "Body": json.dumps({
            "version": 1,
            "job_id": job_id,
            "user_id": user_id,
            "report_type": report_type,
            "params": {},
            "enqueued_at": "2026-04-26T12:00:00+00:00",
            "attempt": attempt,
        }),
        "Attributes": {"ApproximateReceiveCount": str(attempt)},
    }


def test_poison_pill_after_three_attempts_marks_failed_in_dynamodb(jobs_table, s3_bucket, redis_client):
    """Three consecutive deliveries -> FAILED at the third one."""
    from app.models.job import JobPriority
    job = jobs_svc.create_job(
        jobs_table, user_id="u-1", report_type="force_failure",
        priority=JobPriority.STANDARD, params={},
    )
    sqs_mock = MagicMock()

    # Attempt 1: ProcessingError -> back-off 90s, return False
    msg1 = _build_message(job.job_id, attempt=1)
    with patch("worker.processor.simulate_sleep"):
        ack = consumer.handle_message(
            msg1, jobs_table=jobs_table, s3=s3_bucket,
            redis_client=redis_client, bucket="prosperas-reports-test",
            sqs=sqs_mock, queue_url="http://q",
        )
    assert ack is False
    assert sqs_mock.change_message_visibility.call_args.kwargs["VisibilityTimeout"] == 90

    # Job status is still PROCESSING after attempt 1
    j = jobs_svc.get_job(jobs_table, job.job_id)
    assert j.status == JobStatus.PROCESSING

    # Attempt 2: 180s
    msg2 = _build_message(job.job_id, attempt=2)
    sqs_mock.reset_mock()
    with patch("worker.processor.simulate_sleep"):
        ack = consumer.handle_message(
            msg2, jobs_table=jobs_table, s3=s3_bucket,
            redis_client=redis_client, bucket="prosperas-reports-test",
            sqs=sqs_mock, queue_url="http://q",
        )
    assert ack is False
    assert sqs_mock.change_message_visibility.call_args.kwargs["VisibilityTimeout"] == 180

    # Attempt 3: FAILED + ack
    msg3 = _build_message(job.job_id, attempt=3)
    sqs_mock.reset_mock()
    with patch("worker.processor.simulate_sleep"):
        ack = consumer.handle_message(
            msg3, jobs_table=jobs_table, s3=s3_bucket,
            redis_client=redis_client, bucket="prosperas-reports-test",
            sqs=sqs_mock, queue_url="http://q",
        )
    assert ack is True
    sqs_mock.change_message_visibility.assert_not_called()

    final = jobs_svc.get_job(jobs_table, job.job_id)
    assert final.status == JobStatus.FAILED
    assert final.error is not None
    assert "force_failure" in final.error


def test_corrupt_body_returns_false_so_sqs_redrives_to_dlq(jobs_table, s3_bucket, redis_client):
    """A message whose body fails to parse must NOT be acked.

    SQS will redrive it to the DLQ on its own after maxReceiveCount=3.
    We just verify the handler returns False (no ack) on every attempt.
    """
    bad_msg = {
        "MessageId": "m-bad",
        "ReceiptHandle": "rh-bad",
        "Body": "<<this is not json>>",
        "Attributes": {"ApproximateReceiveCount": "3"},
    }
    sqs_mock = MagicMock()

    ack = consumer.handle_message(
        bad_msg, jobs_table=jobs_table, s3=s3_bucket,
        redis_client=redis_client, bucket="prosperas-reports-test",
        sqs=sqs_mock, queue_url="http://q",
    )
    assert ack is False
    sqs_mock.delete_message.assert_not_called()
    sqs_mock.change_message_visibility.assert_not_called()
