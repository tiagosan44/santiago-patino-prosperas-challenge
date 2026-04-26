"""Integration tests for /jobs endpoints (POST, GET, LIST).

Uses TestClient with FastAPI dependency overrides for users_table,
jobs_table, and the SQS client. The S3 client is patched on the
service for the presigned URL test.
"""
import json

import boto3
import pytest
from fastapi.testclient import TestClient

from app.core.aws import reset_clients
from app.main import app
from app.models.job import JobStatus
from app.services import jobs as jobs_svc, users as users_svc


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
def client(users_table, jobs_table, sqs_queues, s3_bucket, monkeypatch):
    """TestClient wired to all the moto-backed fixtures."""
    from app.api import auth as auth_api
    from app.api import jobs as jobs_api
    from app.services import queue as queue_svc

    reset_clients()
    app.dependency_overrides[auth_api.get_users_table] = lambda: users_table
    app.dependency_overrides[jobs_api.get_jobs_table] = lambda: jobs_table
    app.dependency_overrides[jobs_api.get_sqs_client] = lambda: sqs_queues["client"]
    app.dependency_overrides[jobs_api.get_s3_client] = lambda: s3_bucket

    # Route queue URLs to the moto queues
    monkeypatch.setattr(
        queue_svc, "_get_queue_url",
        lambda p: sqs_queues[p.value]
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _login(client, username="alice", password="secret123"):
    res = client.post("/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---- POST /jobs ----

def test_post_jobs_returns_201_and_pending(users_table, client):
    users_svc.create_user(users_table, "alice", "secret123")
    token = _login(client)

    res = client.post("/jobs", json={"report_type": "sales", "format": "json"}, headers=_auth(token))
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["status"] == "PENDING"
    assert data["job_id"]
    assert data["report_type"] == "sales"
    assert data["priority"] == "standard"


def test_post_jobs_routes_high_priority_report_types(users_table, client, sqs_queues):
    users_svc.create_user(users_table, "alice", "secret123")
    token = _login(client)

    res = client.post(
        "/jobs", json={"report_type": "audit", "format": "json"}, headers=_auth(token)
    )
    assert res.status_code == 201
    assert res.json()["priority"] == "high"

    msgs = sqs_queues["client"].receive_message(QueueUrl=sqs_queues["high"], MaxNumberOfMessages=1)
    assert "Messages" in msgs


def test_post_jobs_publishes_to_sqs(users_table, client, sqs_queues):
    users_svc.create_user(users_table, "alice", "secret123")
    token = _login(client)

    res = client.post("/jobs", json={"report_type": "sales", "format": "json"}, headers=_auth(token))
    job_id = res.json()["job_id"]

    msgs = sqs_queues["client"].receive_message(
        QueueUrl=sqs_queues["standard"], MaxNumberOfMessages=1
    )
    assert "Messages" in msgs
    body = json.loads(msgs["Messages"][0]["Body"])
    assert body["job_id"] == job_id


def test_post_jobs_requires_auth(client):
    res = client.post("/jobs", json={"report_type": "sales", "format": "json"})
    assert res.status_code == 401


def test_post_jobs_validates_payload(users_table, client):
    users_svc.create_user(users_table, "alice", "secret123")
    token = _login(client)

    res = client.post("/jobs", json={"format": "json"}, headers=_auth(token))  # missing report_type
    assert res.status_code == 422

    res = client.post("/jobs", json={"report_type": "sales", "format": "doc"}, headers=_auth(token))
    assert res.status_code == 422


# ---- GET /jobs/{id} ----

def test_get_job_returns_job_for_owner(users_table, jobs_table, client):
    user = users_svc.create_user(users_table, "alice", "secret123")
    job = jobs_svc.create_job(
        jobs_table, user_id=user.user_id, report_type="sales",
        priority=jobs_svc.JobPriority.STANDARD if hasattr(jobs_svc, "JobPriority") else None,
        params={},
    ) if False else jobs_svc.create_job(
        jobs_table, user_id=user.user_id, report_type="sales",
        priority=__import__("app.models.job", fromlist=["JobPriority"]).JobPriority.STANDARD,
        params={},
    )
    token = _login(client)
    res = client.get(f"/jobs/{job.job_id}", headers=_auth(token))
    assert res.status_code == 200, res.text
    assert res.json()["job_id"] == job.job_id


def test_get_job_returns_404_for_other_users_job(users_table, jobs_table, client):
    from app.models.job import JobPriority
    users_svc.create_user(users_table, "alice", "secret123")
    bob = users_svc.create_user(users_table, "bob", "secret123")
    job = jobs_svc.create_job(jobs_table, bob.user_id, "sales", JobPriority.STANDARD, {})

    token = _login(client, "alice", "secret123")
    res = client.get(f"/jobs/{job.job_id}", headers=_auth(token))
    assert res.status_code == 404


def test_get_job_returns_404_for_missing(users_table, client):
    users_svc.create_user(users_table, "alice", "secret123")
    token = _login(client)
    res = client.get("/jobs/nonexistent", headers=_auth(token))
    assert res.status_code == 404


def test_get_job_returns_presigned_url_when_completed(users_table, jobs_table, client, s3_bucket):
    from app.models.job import JobPriority
    user = users_svc.create_user(users_table, "alice", "secret123")
    job = jobs_svc.create_job(jobs_table, user.user_id, "sales", JobPriority.STANDARD, {})
    # Upload a fake result and update the job
    s3_bucket.put_object(
        Bucket="prosperas-reports-test",
        Key=f"reports/{user.user_id}/{job.job_id}/result.json",
        Body=b'{"data": "dummy"}',
    )
    jobs_svc.update_job_status(
        jobs_table, job_id=job.job_id, expected_version=1,
        status=JobStatus.COMPLETED,
        result_url=f"reports/{user.user_id}/{job.job_id}/result.json",
    )

    token = _login(client)
    res = client.get(f"/jobs/{job.job_id}", headers=_auth(token))
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "COMPLETED"
    # The response must contain a presigned HTTP URL, not just the S3 key
    assert data["result_url"].startswith("http")
    assert "Signature" in data["result_url"] or "X-Amz-Signature" in data["result_url"]


# ---- GET /jobs (list) ----

def test_list_jobs_returns_only_owners_jobs(users_table, jobs_table, client):
    from app.models.job import JobPriority
    alice = users_svc.create_user(users_table, "alice", "secret123")
    bob = users_svc.create_user(users_table, "bob", "secret123")
    jobs_svc.create_job(jobs_table, alice.user_id, "sales", JobPriority.STANDARD, {})
    jobs_svc.create_job(jobs_table, alice.user_id, "audit", JobPriority.HIGH, {})
    jobs_svc.create_job(jobs_table, bob.user_id, "sales", JobPriority.STANDARD, {})

    token = _login(client, "alice", "secret123")
    res = client.get("/jobs", headers=_auth(token))
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) == 2
    assert data["next_cursor"] is None


def test_list_jobs_paginates(users_table, jobs_table, client):
    from app.models.job import JobPriority
    user = users_svc.create_user(users_table, "alice", "secret123")
    for _ in range(3):
        jobs_svc.create_job(jobs_table, user.user_id, "sales", JobPriority.STANDARD, {})

    token = _login(client)
    res = client.get("/jobs?limit=2", headers=_auth(token))
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) == 2
    assert data["next_cursor"] is not None

    res2 = client.get(f"/jobs?limit=2&cursor={data['next_cursor']}", headers=_auth(token))
    data2 = res2.json()
    assert len(data2["items"]) == 1
