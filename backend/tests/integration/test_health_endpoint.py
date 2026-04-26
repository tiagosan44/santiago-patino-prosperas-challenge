"""Integration tests for /health endpoint with dependency checks."""
import boto3
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def health_setup(jobs_table, monkeypatch):
    """Set up the /health dependencies (jobs table, sqs, s3, redis)."""
    from app.api import health as health_api
    from app.core.aws import reset_clients

    sqs = boto3.client("sqs", region_name="us-east-1")
    sqs.create_queue(QueueName="jobs-high")
    sqs.create_queue(QueueName="jobs-standard")
    sqs.create_queue(QueueName="jobs-dlq")

    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="prosperas-reports-test")

    # Redis is not available in the moto test environment; stub it out so
    # the overall health result is determined by the AWS deps only.
    monkeypatch.setattr(health_api, "_check_redis", lambda: None)

    reset_clients()
    yield


@pytest.fixture
def client(aws, health_setup):
    from app.main import app
    return TestClient(app)


def test_health_returns_200_when_all_deps_ok(client):
    """All dependencies healthy: status=healthy, all dep statuses 'healthy'."""
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "healthy"
    assert "deps" in body
    deps = body["deps"]
    assert deps["dynamodb"] == "healthy"
    assert deps["sqs_high"] == "healthy"
    assert deps["sqs_standard"] == "healthy"
    assert deps["sqs_dlq"] == "healthy"
    assert deps["s3"] == "healthy"
    # redis may or may not be reachable in unit tests; check presence either way
    assert "redis" in deps
    assert "version" in body


def test_health_returns_503_when_dynamodb_is_down(client, monkeypatch):
    """Simulate DynamoDB failure: monkey-patch the check function to raise."""
    from app.api import health as health_api

    def boom():
        raise RuntimeError("simulated dynamodb outage")

    monkeypatch.setattr(health_api, "_check_dynamodb", boom)

    res = client.get("/health")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "unhealthy"
    assert body["deps"]["dynamodb"] != "healthy"


def test_health_returns_503_when_redis_is_down(client, monkeypatch):
    from app.api import health as health_api

    def boom():
        raise RuntimeError("simulated redis outage")

    monkeypatch.setattr(health_api, "_check_redis", boom)

    res = client.get("/health")
    assert res.status_code == 503
    body = res.json()
    assert body["deps"]["redis"] != "healthy"


def test_health_includes_version_field(client):
    """Version field comes from settings.git_sha (default 'dev' locally)."""
    res = client.get("/health")
    body = res.json()
    assert body["version"] == "dev"


def test_health_includes_x_request_id_header(client):
    """The middleware adds X-Request-ID to every response, including /health."""
    res = client.get("/health")
    assert "x-request-id" in {k.lower() for k in res.headers.keys()}
