"""Shared pytest fixtures.

Sets minimum environment variables before importing the app (so
`Settings()` validation passes), and provides a `mock_aws` fixture
that creates DynamoDB tables / SQS queues / S3 bucket / SNS topic in
memory using moto.
"""
import os

# Set required env vars BEFORE any app module is imported. The Settings
# class validates on construction, so missing vars would raise.
os.environ.setdefault("SQS_HIGH_QUEUE_URL", "http://moto/jobs-high")
os.environ.setdefault("SQS_STANDARD_QUEUE_URL", "http://moto/jobs-standard")
os.environ.setdefault("SQS_DLQ_URL", "http://moto/jobs-dlq")
os.environ.setdefault("S3_REPORTS_BUCKET", "prosperas-reports-test")
os.environ.setdefault("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:000000000000:job-updates-test")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
# Disable any real endpoint override during tests so moto's mocks intercept.
os.environ.pop("AWS_ENDPOINT_URL", None)

import boto3  # noqa: E402  (import after env setup is intentional)
import pytest  # noqa: E402
from moto import mock_aws  # noqa: E402


@pytest.fixture
def aws():
    """Activates moto's mock for the duration of the test."""
    with mock_aws():
        yield


@pytest.fixture
def users_table(aws):
    db = boto3.resource("dynamodb", region_name="us-east-1")
    table = db.create_table(
        TableName="users",
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "username", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "username-index",
                "KeySchema": [{"AttributeName": "username", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


@pytest.fixture
def jobs_table(aws):
    db = boto3.resource("dynamodb", region_name="us-east-1")
    table = db.create_table(
        TableName="jobs",
        AttributeDefinitions=[
            {"AttributeName": "job_id", "AttributeType": "S"},
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "created_at", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "user-created-index",
                "KeySchema": [
                    {"AttributeName": "user_id", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "status-created-index",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table
