"""Application settings loaded from environment variables.

Pydantic Settings reads `.env` (when present) and `os.environ`. All
required vars must be set in production; for local development a
`.env` file copied from `.env.example` is enough.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    # AWS
    aws_region: str = "us-east-1"
    aws_endpoint_url: str | None = None  # None in prod; http://localstack:4566 locally
    aws_access_key_id: str | None = None  # boto3 picks from env or ~/.aws/credentials
    aws_secret_access_key: str | None = None

    # DynamoDB tables
    dynamodb_users_table: str = "users"
    dynamodb_jobs_table: str = "jobs"

    # SQS queue URLs
    sqs_high_queue_url: str
    sqs_standard_queue_url: str
    sqs_dlq_url: str

    # S3
    s3_reports_bucket: str

    # SNS
    sns_topic_arn: str

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Auth
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60

    # Worker
    worker_concurrency: int = 4

    # Logging
    log_level: str = "INFO"

    # Build metadata (set by CI; "dev" locally)
    git_sha: str = "dev"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached factory — call this from anywhere in the app.

    Tests can clear the cache with `get_settings.cache_clear()` if they
    need to inject different env vars.
    """
    return Settings()
