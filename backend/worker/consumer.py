"""Synchronous SQS consumer.

Polls jobs-high first (short long-poll) then jobs-standard (full
long-poll). This is "priority with fairness": when high is empty,
workers don't sit idle — they consume standard. The compromise is
that a flood of standard messages briefly delays standard processing,
which is acceptable.

handle_message is the per-message workflow: read job from DynamoDB,
transition to PROCESSING with optimistic locking, run the processor,
transition to COMPLETED (or FAILED on ProcessingError), publish an
SNS event for real-time updates.

Async upgrade with aioboto3 lands in Task 3.3 (4 concurrent tasks per
container).
"""
import json
import logging
from typing import Any

from app.core.config import get_settings
from app.models.job import JobStatus
from app.services import jobs as jobs_svc
from . import processor

logger = logging.getLogger(__name__)


# ----- queue URL helpers (patched in tests) -----

def _high_queue_url() -> str:
    return get_settings().sqs_high_queue_url


def _standard_queue_url() -> str:
    return get_settings().sqs_standard_queue_url


# ----- polling -----

def poll_next_message(sqs, wait_high: int = 1, wait_standard: int = 20) -> dict | None:
    """Poll high then standard. Returns the message dict or None."""
    res = sqs.receive_message(
        QueueUrl=_high_queue_url(),
        MaxNumberOfMessages=1,
        WaitTimeSeconds=wait_high,
        AttributeNames=["ApproximateReceiveCount"],
    )
    msgs = res.get("Messages", [])
    if msgs:
        return msgs[0]

    res = sqs.receive_message(
        QueueUrl=_standard_queue_url(),
        MaxNumberOfMessages=1,
        WaitTimeSeconds=wait_standard,
        AttributeNames=["ApproximateReceiveCount"],
    )
    msgs = res.get("Messages", [])
    return msgs[0] if msgs else None


# ----- per-message handler -----

def _publish_event(sns, topic_arn: str, *, job, event_status: str) -> None:
    """Publish a job-update event for SSE fan-out."""
    payload = {
        "event": "job-update",
        "job_id": job.job_id,
        "user_id": job.user_id,
        "status": event_status,
        "result_url": job.result_url,
        "error": job.error,
        "updated_at": job.updated_at,
    }
    try:
        sns.publish(TopicArn=topic_arn, Message=json.dumps(payload))
    except Exception:  # noqa: BLE001
        # SNS is best-effort for real-time; failing it should NOT roll
        # back the DynamoDB transition. Log and move on.
        logger.exception("failed to publish SNS event for job %s", job.job_id)


def handle_message(
    message: dict[str, Any],
    *,
    jobs_table,
    s3,
    sns,
    bucket: str,
    topic_arn: str,
) -> bool:
    """Process one SQS message.

    Returns True if the caller should delete the message from SQS, or
    False to leave it (and let SQS retry / eventually DLQ).
    """
    # 1. Parse body
    try:
        body = json.loads(message["Body"])
        job_id = body["job_id"]
    except (json.JSONDecodeError, KeyError):
        logger.exception("unparseable SQS body, leaving for retry/DLQ")
        return False

    # 2. Lookup job
    job = jobs_svc.get_job(jobs_table, job_id)
    if job is None:
        logger.warning("job %s not found, ack message (poison)", job_id)
        return True

    # 3. Skip if already terminal
    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
        logger.info("job %s already %s, ack duplicate", job_id, job.status)
        return True

    # 4. Transition to PROCESSING with optimistic lock
    try:
        job = jobs_svc.update_job_status(
            jobs_table,
            job_id=job_id,
            expected_version=job.version,
            status=JobStatus.PROCESSING,
            increment_attempts=True,
        )
    except jobs_svc.OptimisticLockError:
        logger.info("job %s optimistic lock conflict, ack duplicate", job_id)
        return True

    # 5. Process (S3 upload, possibly raises ProcessingError)
    try:
        result_url = processor.process_job(
            s3=s3,
            bucket=bucket,
            user_id=job.user_id,
            job_id=job.job_id,
            report_type=job.report_type,
            params=job.params,
        )
    except processor.ProcessingError as e:
        logger.warning("job %s processing failed: %s", job_id, e)
        error_msg = f"[{job.report_type}] {e}"
        try:
            failed_job = jobs_svc.update_job_status(
                jobs_table,
                job_id=job_id,
                expected_version=job.version,
                status=JobStatus.FAILED,
                error=error_msg,
            )
        except jobs_svc.OptimisticLockError:
            logger.warning("could not write FAILED for job %s (lock conflict)", job_id)
            return True
        _publish_event(sns, topic_arn, job=failed_job, event_status="FAILED")
        return True
    except Exception:  # noqa: BLE001
        logger.exception("unexpected error processing job %s, leaving for retry", job_id)
        return False

    # 6. Transition to COMPLETED
    try:
        completed_job = jobs_svc.update_job_status(
            jobs_table,
            job_id=job_id,
            expected_version=job.version,
            status=JobStatus.COMPLETED,
            result_url=result_url,
        )
    except jobs_svc.OptimisticLockError:
        logger.warning("could not write COMPLETED for job %s (lock conflict)", job_id)
        return True

    _publish_event(sns, topic_arn, job=completed_job, event_status="COMPLETED")
    return True
