---
name: prosperas-reports
description: Async report processing system — Python/FastAPI backend with SQS workers, React frontend with SSE real-time updates, deployed to AWS via Terraform.
---

# Prosperas Reports — agent context

> Read this when starting any task that touches the codebase. It tells you what's where, the common commands, and the gotchas.

## What this is

A take-home challenge implementation: users submit a report request via the React frontend; the FastAPI backend persists the request in DynamoDB and enqueues to SQS; one of the worker tasks processes it (simulated 5–30s sleep), uploads a JSON result to S3, and updates DynamoDB. The frontend sees status changes in real time via SSE. Full CI/CD deploys to AWS via Terraform.

## Project layout (high level)

- `backend/app/` — FastAPI app (auth, jobs, events, health routers; pydantic models; services; core: config, aws clients, security, errors, middleware, structlog config, metrics)
- `backend/worker/` — async worker entrypoint (`main.py`), per-message handler (`consumer.py`), pure processor (`processor.py`), shared circuit breaker (`circuit_breaker.py`)
- `backend/tests/{unit,integration}/` — pytest with moto (in-memory AWS mocks) and LocalStack
- `frontend/src/` — Vite + React 18 + TypeScript + Tailwind 3; Zustand stores; SSE hook
- `frontend/tests/{*.test.ts,e2e/}` — Vitest unit + Playwright E2E
- `local/docker-compose.yml` — full local stack (LocalStack + Redis + api + worker + frontend)
- `infra/terraform/modules/{...}/` — 11 modules
- `infra/terraform/environments/prod/` — composition root with S3/Dynamo backend
- `.github/workflows/{pr,deploy}.yml` — CI/CD

## Common commands

### Run everything locally
```bash
cd local && docker compose up --build
```

### Backend tests
```bash
cd backend
docker run --rm -v "$(pwd):/app" -w /app prosperas-api:dev \
  bash -c "pip install -q -r requirements-dev.txt && pytest --cov=app --cov=worker"
```

Coverage threshold (`fail_under = 70`) is enforced in `pyproject.toml`.

### Frontend unit tests
```bash
cd frontend && npm test
```

### Frontend E2E (requires full stack up)
```bash
cd frontend && npm run e2e
```

### Terraform validate (no apply)
```bash
cd infra/terraform/environments/prod
terraform init -input=false
terraform validate
```

### Build + push images manually
```bash
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin <ACCOUNT>.dkr.ecr.us-east-1.amazonaws.com
docker build -t <ACCOUNT>.dkr.ecr.us-east-1.amazonaws.com/prosperas-api:latest backend/
docker push <ACCOUNT>.dkr.ecr.us-east-1.amazonaws.com/prosperas-api:latest
```

## Critical environment variables

See `.env.example`. The backend services validate them on startup via `pydantic-settings`.

| Var | Purpose |
|---|---|
| `AWS_ENDPOINT_URL` | Set to `http://localstack:4566` locally; unset in prod |
| `SQS_HIGH_QUEUE_URL` / `SQS_STANDARD_QUEUE_URL` / `SQS_DLQ_URL` | Queue URLs |
| `DYNAMODB_USERS_TABLE` / `DYNAMODB_JOBS_TABLE` | Table names |
| `S3_REPORTS_BUCKET` | Bucket for results |
| `SNS_TOPIC_ARN` | Forward-compatibility hook (currently unused; Redis handles fan-out) |
| `REDIS_URL` | `redis://redis:6379/0` locally, `redis://redis.prosperas.local:6379/0` in prod |
| `JWT_SECRET` | HS256 signing key |
| `WORKER_CONCURRENCY` | Number of asyncio tasks per worker container (default 4) |
| `GIT_SHA` | Set by CI; surfaced in `/health` `version` |

## Gotchas

- **Python 3.12 only.** The worker uses `asyncio.to_thread` (3.9+) and the codebase uses `from datetime import UTC` (3.11+).
- **The .env file is gitignored**; copy `.env.example` to `.env` for local dev.
- **Pre-commit hook (gitleaks)** scans every commit for secrets. If it complains, fix the leak rather than bypassing.
- **Tests use moto for unit + LocalStack for integration.** Do not make tests depend on real AWS.
- **The worker's `force_failure` report_type is a test hook** — it's the easiest way to demo the FAILED state in the UI.
- **SSE JWT is passed via `?token=` query param** (not a header) because the browser `EventSource` API doesn't support custom headers. This is documented as a minor security limitation in TECHNICAL_DOCS.md.

## When something breaks

- **Frontend can't talk to API:** check the CORS config in `backend/app/main.py` and that `VITE_API_URL` is set correctly.
- **LocalStack tables/queues missing:** `docker compose down -v` and bring up again so the `init-aws` sidecar re-runs the resource creation scripts.
- **Terraform apply complaining about state lock:** the lock is in the `prosperas-tflock` DynamoDB table — `terraform force-unlock <lock-id>` if a previous apply was killed mid-flight.
- **ECS tasks failing to start:** check `aws logs tail /ecs/prosperas/api --since 5m` for startup errors.
- **Worker not picking up messages:** check the security group allows egress, the IAM role has `sqs:ReceiveMessage` on the queue ARNs, and the queue URLs in env match the actual queue names (not the DLQ).
- **SSE stream closes immediately:** the ALB idle timeout is 60s; the API sends a keepalive comment every 15s. If streams close sooner, check that the heartbeat task is running (log line `"event": "sse_heartbeat_started"`).
- **Circuit breaker stuck OPEN:** the recovery window is 60s. If you need to reset it manually in local dev, run `redis-cli del circuit_breakers:<report_type>`.

## How to extend

- **New report type:** add to `HIGH_PRIORITY_REPORT_TYPES` in `backend/app/services/queue.py` if it needs high-priority routing; add to the form's `REPORT_TYPES` constant in `frontend/src/components/JobForm.tsx`. Nothing else is needed — the processor's `generate_dummy_data` has a generic fallback.
- **New endpoint:** create a router in `backend/app/api/`, include it in `main.py`. Use `Depends(get_current_user)` for auth and the AWS factory functions in `backend/app/core/aws.py` for table/client access. Write tests in `backend/tests/integration/`.
- **New AWS service:** add a Terraform module under `infra/terraform/modules/`, wire it into `infra/terraform/environments/prod/main.tf`, and update `outputs.tf`. Add the necessary IAM permissions to the relevant task role in the `iam` module.
- **New metric:** call `metrics.increment("prosperas.your_metric", tags={"dim": value})` from anywhere in the backend. The `metrics` module wraps CloudWatch `put_metric_data` with buffering.

## Out of scope (intentionally not implemented)

- JWT refresh tokens / revocation list
- Rate limiting per user
- Distributed tracing (X-Ray / OTel)
- Multi-region failover
- Redis persistence / clustering
- WebSocket bi-directional channel (SSE is one-way and sufficient)
- Job cancellation endpoint
- OpenSearch / ELK centralized log aggregation
- Frontend internationalization
