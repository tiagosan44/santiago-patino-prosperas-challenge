#!/bin/sh
# Initializes AWS resources in LocalStack on first docker-compose up.
# Idempotent: re-running does NOT fail (each create command suppresses
# AlreadyExists errors with `|| true`).
set -e
ENDPOINT="--endpoint-url=http://localstack:4566"
REGION="--region us-east-1"
ACCOUNT="000000000000"

echo "[init-aws] Waiting for LocalStack to be ready..."
until aws $ENDPOINT $REGION sts get-caller-identity > /dev/null 2>&1; do
  sleep 1
done
echo "[init-aws] LocalStack ready."

# ----- DynamoDB tables -----

echo "[init-aws] Creating DynamoDB table: users"
aws $ENDPOINT $REGION dynamodb create-table \
  --table-name users \
  --attribute-definitions \
    AttributeName=user_id,AttributeType=S \
    AttributeName=username,AttributeType=S \
  --key-schema AttributeName=user_id,KeyType=HASH \
  --global-secondary-indexes '[{
    "IndexName": "username-index",
    "KeySchema": [{"AttributeName": "username", "KeyType": "HASH"}],
    "Projection": {"ProjectionType": "ALL"}
  }]' \
  --billing-mode PAY_PER_REQUEST 2>/dev/null || echo "[init-aws] users table already exists"

echo "[init-aws] Creating DynamoDB table: jobs"
aws $ENDPOINT $REGION dynamodb create-table \
  --table-name jobs \
  --attribute-definitions \
    AttributeName=job_id,AttributeType=S \
    AttributeName=user_id,AttributeType=S \
    AttributeName=created_at,AttributeType=S \
    AttributeName=status,AttributeType=S \
  --key-schema AttributeName=job_id,KeyType=HASH \
  --global-secondary-indexes '[
    {
      "IndexName": "user-created-index",
      "KeySchema": [
        {"AttributeName": "user_id", "KeyType": "HASH"},
        {"AttributeName": "created_at", "KeyType": "RANGE"}
      ],
      "Projection": {"ProjectionType": "ALL"}
    },
    {
      "IndexName": "status-created-index",
      "KeySchema": [
        {"AttributeName": "status", "KeyType": "HASH"},
        {"AttributeName": "created_at", "KeyType": "RANGE"}
      ],
      "Projection": {"ProjectionType": "ALL"}
    }
  ]' \
  --billing-mode PAY_PER_REQUEST 2>/dev/null || echo "[init-aws] jobs table already exists"

# ----- SQS queues -----

echo "[init-aws] Creating SQS DLQ"
aws $ENDPOINT $REGION sqs create-queue --queue-name jobs-dlq 2>/dev/null || true
DLQ_URL="http://localstack:4566/${ACCOUNT}/jobs-dlq"
DLQ_ARN=$(aws $ENDPOINT $REGION sqs get-queue-attributes \
  --queue-url "$DLQ_URL" \
  --attribute-names QueueArn \
  --query 'Attributes.QueueArn' \
  --output text)
echo "[init-aws] DLQ ARN: $DLQ_ARN"

# Build redrive policy. Note: nested JSON inside SQS attributes must be
# serialized as a string, so we escape the inner quotes.
REDRIVE="{\"deadLetterTargetArn\":\"$DLQ_ARN\",\"maxReceiveCount\":\"3\"}"
ATTRS_FILE=$(mktemp)
cat > "$ATTRS_FILE" <<EOF
{
  "VisibilityTimeout": "90",
  "RedrivePolicy": "$(echo "$REDRIVE" | sed 's/"/\\"/g')"
}
EOF

for q in jobs-high jobs-standard; do
  echo "[init-aws] Creating SQS: $q"
  aws $ENDPOINT $REGION sqs create-queue \
    --queue-name "$q" \
    --attributes "file://$ATTRS_FILE" 2>/dev/null || echo "[init-aws] $q already exists"
done

# ----- S3 bucket -----

echo "[init-aws] Creating S3 bucket: prosperas-reports-local"
aws $ENDPOINT $REGION s3 mb s3://prosperas-reports-local 2>/dev/null || echo "[init-aws] bucket already exists"

# ----- SNS topic -----

echo "[init-aws] Creating SNS topic: job-updates"
aws $ENDPOINT $REGION sns create-topic --name job-updates 2>/dev/null || echo "[init-aws] topic already exists"

echo "[init-aws] Initialization complete. Resources:"
aws $ENDPOINT $REGION dynamodb list-tables --output text
aws $ENDPOINT $REGION sqs list-queues --output text
aws $ENDPOINT $REGION s3 ls
aws $ENDPOINT $REGION sns list-topics --output text
