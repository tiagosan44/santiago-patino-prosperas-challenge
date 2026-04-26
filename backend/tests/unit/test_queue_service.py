"""Unit tests for the SQS publisher.

Verifies routing logic (high vs standard) and message body shape.
Uses moto's mock SQS for verification.
"""
import json

import boto3
import pytest

from app.models.job import JobPriority
from app.services import queue as queue_svc


HIGH_REPORTS = {"executive_summary", "audit"}


@pytest.fixture
def sqs_queues(aws):
    """Create the three queues in moto and return their URLs."""
    sqs = boto3.client("sqs", region_name="us-east-1")
    high = sqs.create_queue(QueueName="jobs-high")["QueueUrl"]
    standard = sqs.create_queue(QueueName="jobs-standard")["QueueUrl"]
    dlq = sqs.create_queue(QueueName="jobs-dlq")["QueueUrl"]
    return {"high": high, "standard": standard, "dlq": dlq, "client": sqs}


def test_priority_for_report_type_routes_special_types_to_high():
    assert queue_svc.priority_for_report_type("audit") == JobPriority.HIGH
    assert queue_svc.priority_for_report_type("executive_summary") == JobPriority.HIGH


def test_priority_for_report_type_routes_default_to_standard():
    assert queue_svc.priority_for_report_type("sales") == JobPriority.STANDARD
    assert queue_svc.priority_for_report_type("inventory") == JobPriority.STANDARD


def test_publish_job_sends_to_high_queue(sqs_queues, monkeypatch):
    monkeypatch.setattr(queue_svc, "_get_queue_url", lambda p: sqs_queues[p.value])
    queue_svc.publish_job(
        sqs_queues["client"],
        job_id="abc",
        user_id="u-1",
        report_type="audit",
        priority=JobPriority.HIGH,
        params={"format": "json"},
    )
    msgs = sqs_queues["client"].receive_message(QueueUrl=sqs_queues["high"], MaxNumberOfMessages=1)
    assert "Messages" in msgs
    body = json.loads(msgs["Messages"][0]["Body"])
    assert body["job_id"] == "abc"
    assert body["user_id"] == "u-1"
    assert body["report_type"] == "audit"
    assert body["params"] == {"format": "json"}
    assert body["attempt"] == 1
    assert body["version"] == 1
    assert "enqueued_at" in body


def test_publish_job_sends_to_standard_queue(sqs_queues, monkeypatch):
    monkeypatch.setattr(queue_svc, "_get_queue_url", lambda p: sqs_queues[p.value])
    queue_svc.publish_job(
        sqs_queues["client"],
        job_id="def",
        user_id="u-1",
        report_type="sales",
        priority=JobPriority.STANDARD,
        params={},
    )
    msgs = sqs_queues["client"].receive_message(QueueUrl=sqs_queues["standard"], MaxNumberOfMessages=1)
    assert "Messages" in msgs
    high_msgs = sqs_queues["client"].receive_message(QueueUrl=sqs_queues["high"], MaxNumberOfMessages=1)
    assert "Messages" not in high_msgs
