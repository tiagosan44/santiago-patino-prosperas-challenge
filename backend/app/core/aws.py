"""boto3 / aioboto3 client factories.

All clients honor the optional `aws_endpoint_url` setting so the same
code runs against LocalStack in development and real AWS in
production. Clients are cached per process so we don't open a new HTTP
session for every request.
"""
from functools import lru_cache

import boto3

from .config import get_settings


def _client_kwargs() -> dict:
    settings = get_settings()
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    # boto3 will pick up access_key_id / secret_access_key from env or
    # ~/.aws/credentials automatically. We only pass them explicitly if
    # set in settings (LocalStack accepts any value).
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return kwargs


@lru_cache(maxsize=1)
def dynamo_resource():
    return boto3.resource("dynamodb", **_client_kwargs())


def users_table():
    return dynamo_resource().Table(get_settings().dynamodb_users_table)


def jobs_table():
    return dynamo_resource().Table(get_settings().dynamodb_jobs_table)


@lru_cache(maxsize=1)
def sqs_client():
    return boto3.client("sqs", **_client_kwargs())


@lru_cache(maxsize=1)
def s3_client():
    return boto3.client("s3", **_client_kwargs())


@lru_cache(maxsize=1)
def sns_client():
    return boto3.client("sns", **_client_kwargs())


@lru_cache(maxsize=1)
def cloudwatch_client():
    return boto3.client("cloudwatch", **_client_kwargs())


def reset_clients() -> None:
    """For tests: clears all cached clients so the next call rebuilds them."""
    dynamo_resource.cache_clear()
    sqs_client.cache_clear()
    s3_client.cache_clear()
    sns_client.cache_clear()
    cloudwatch_client.cache_clear()
    get_settings.cache_clear()
