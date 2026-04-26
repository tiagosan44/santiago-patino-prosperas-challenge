#!/usr/bin/env python3
"""Create a test user in LocalStack DynamoDB.

Usage:
    python scripts/seed_user.py <username> <password>

Default: alice / secret123 if no args.
"""
import os
import sys
from pathlib import Path

# Make backend imports resolvable from this script
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# Configure for LocalStack — point at host.docker.internal port 4566
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_ENDPOINT_URL", "http://localhost:4566")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("SQS_HIGH_QUEUE_URL", "http://localhost:4566/000000000000/jobs-high")
os.environ.setdefault("SQS_STANDARD_QUEUE_URL", "http://localhost:4566/000000000000/jobs-standard")
os.environ.setdefault("SQS_DLQ_URL", "http://localhost:4566/000000000000/jobs-dlq")
os.environ.setdefault("S3_REPORTS_BUCKET", "prosperas-reports-local")
os.environ.setdefault("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:000000000000:job-updates")
os.environ.setdefault("JWT_SECRET", "local-dev-secret-CHANGE-IN-PROD")

from app.core import aws  # noqa: E402
from app.services import users as users_svc  # noqa: E402


def main():
    username = sys.argv[1] if len(sys.argv) > 1 else "alice"
    password = sys.argv[2] if len(sys.argv) > 2 else "secret123"

    table = aws.users_table()

    existing = users_svc.get_by_username(table, username)
    if existing:
        print(f"User already exists: user_id={existing.user_id}")
        return

    user = users_svc.create_user(table, username, password)
    print(f"Created user_id={user.user_id} username={user.username}")
    print(f"Login with: curl -X POST http://localhost:8000/auth/login \\")
    print(f"  -H 'Content-Type: application/json' \\")
    print(f"  -d '{{\"username\":\"{username}\",\"password\":\"{password}\"}}'")


if __name__ == "__main__":
    main()
