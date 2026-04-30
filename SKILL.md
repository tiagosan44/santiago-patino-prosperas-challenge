---
name: prosperas-reports
description: Async report processing system — Python/FastAPI backend with SQS workers, React frontend with SSE real-time updates, deployed to AWS via Terraform.
---

# Prosperas Reports — agent context

> Read this when starting any task that touches the codebase. It tells you what's where, the common commands, and the gotchas.

## What this is

A take-home challenge implementation: users submit a report request via the React frontend; the FastAPI backend persists the request in DynamoDB and enqueues to SQS; one of the worker tasks processes it (simulated 5–30s sleep), uploads a JSON result to S3, and updates DynamoDB. The frontend sees status changes in real time via SSE. Full CI/CD deploys to AWS via Terraform.

## AWS services and why each was chosen

| Service | Used for | Why this and not the alternative |
|---|---|---|
| **SQS** (3 queues: `jobs-high`, `jobs-standard`, `jobs-dlq`) | Async job dispatch + DLQ | At-least-once delivery, visibility timeout for back-off, native redrive policy → DLQ. Picked over SNS/EventBridge because we need *consumed* messages, not fan-out. Picked over Kinesis because volumes are low and per-message ack semantics fit better. |
| **DynamoDB** (multi-table: `users`, `jobs`) | Job + user state | Single-digit ms reads, no schema migrations, fits the access pattern (get-by-id, list-by-user). Multi-table over single-table because the entity count is small and explicit GSIs are easier to reason about than a packed PK/SK encoding. |
| **ECS Fargate** | API + worker containers | Long-running tasks (5–30s up to several minutes) sit awkwardly for Lambda's 15-min cap and cold starts; Fargate runs the same container image we test locally. Same image in dev/prod is the whole point. |
| **S3** (private bucket, lifecycle 30d) | Report results | Cheap durable blob store. Result URLs in `JobResponse` are presigned (15 min expiry) so the client gets time-bounded access without us proxying bytes through the API. |
| **CloudFront** (default cert) | Frontend HTTPS + (in progress) API HTTPS | Fastest path to free HTTPS without a custom domain + ACM. Frontend is fronted today; API is being added as a second origin to fix Mixed Content. |
| **ALB** | API ingress (HTTP→ECS) | Health checks, path-based routing, SSE-friendly idle timeout (60s). |
| **ElastiCache-equivalent Redis on Fargate Spot** (ephemeral) | Pub/sub for SSE fan-out + circuit breaker shared state | Picked Redis-on-Fargate over ElastiCache to stay in free tier; ephemeral is acceptable because both use cases tolerate cold-start (clients reconnect, breakers default to CLOSED). |
| **CloudWatch Logs + Metrics** | Structured logs + business metrics (`prosperas.job_created`, `job_completed`, `job_failed`, etc.) | Default for ECS, no extra plumbing. Metrics are emitted via buffered `put_metric_data`. |
| **SNS** (alarms only) | DLQ depth alarm → email | Single subscriber, low volume; SES would be overkill. |
| **ECR** | Docker image registry | Default for ECS Fargate. |
| **IAM** (per-service roles) | Least-privilege task roles | API role: read/write DDB, send to SQS, read from S3. Worker role: read SQS, read/write DDB, write to S3. |

The high-level rule: **stay inside the free tier, prefer container parity with local, avoid services that hide concurrency.**

## Worker state machine and failure handling

Per-message flow in `backend/worker/consumer.py::handle_message`:

1. **Parse SQS body**, extract `job_id`. Unparseable → return False (leave for SQS to retry / DLQ).
2. **Lookup job in DynamoDB**. If not found → ack the message (poison message protection).
3. **Skip terminal states.** If job is already `COMPLETED` or `FAILED`, ack as duplicate.
4. **Circuit breaker check** (`circuit_breaker.allow`): if the breaker for this `report_type` is OPEN in Redis, extend visibility 60s and leave the message → another worker will retry once breaker may have transitioned to HALF_OPEN. The breaker state is shared across replicas via Redis `WATCH` + `MULTI`/`EXEC` (optimistic transaction — if another worker modifies the key between WATCH and EXEC the transaction aborts and we retry, so two concurrent failures can't both bypass the threshold).
5. **Optimistic transition `PENDING → PROCESSING`** via DynamoDB `update_item` with `ConditionExpression` on `version`. If the conditional write fails (`OptimisticLockError`), another worker grabbed it first → ack the duplicate.
6. **Run processor** (`processor.process_job`): simulated 5–30s sleep + dummy data → upload JSON to S3, return the S3 key.
7. **On `ProcessingError`:**
   - Increment circuit breaker failure counter.
   - Read `ApproximateReceiveCount` from the SQS message attributes.
   - If `receive_count < 3`: extend visibility with **exponential back-off** (90s, 180s, 360s, capped at 900s) via `change_message_visibility` → return False → SQS will redeliver after the delay.
   - If `receive_count >= 3`: write `FAILED` to DynamoDB with the error string, publish a Redis event so the UI shows it, ack the message. (Note: SQS redrive policy `maxReceiveCount=3` would also send it to DLQ on the next receive; we mark FAILED first so the user sees the failure regardless of DLQ alarm timing.)
8. **On any other unexpected exception:** log, return False so SQS handles retry. Don't ack — we don't know if the side effects (S3 upload) succeeded.
9. **Success path:** transition `PROCESSING → COMPLETED` (also optimistic-locked), record breaker success, publish Redis event, emit `job_completed` + `job_processing_duration_seconds` metrics.

State transitions allowed: `PENDING → PROCESSING → COMPLETED | FAILED`. No others. Direct `PENDING → FAILED` only happens after exhausting retries on the *first* `PROCESSING` attempt of each delivery.

Concurrency: each worker container runs **N asyncio tasks** (`WORKER_CONCURRENCY`, default 4), all sharing one SQS client. The blocking `boto3` calls are wrapped in `asyncio.to_thread`. Two replicas → 8 concurrent jobs cluster-wide by default.

## Endpoint contracts

All API endpoints are mounted at the root. Auth uses HS256 JWT in `Authorization: Bearer <token>` (except SSE — see below).

### `POST /auth/login`
**Request:** `{ "username": str, "password": str }`
**Response 200:** `{ "access_token": str, "token_type": "bearer" }` — token expires in 60 min (`JWT_EXPIRY_MINUTES`).
**Errors:** 401 on bad credentials.

### `POST /jobs` (auth required)
**Request:**
```json
{ "report_type": "sales", "date_range": "2026-01-01..2026-04-01", "format": "json" }
```
- `report_type`: 1–64 chars
- `date_range`: optional string (free-form)
- `format`: `"json" | "csv" | "pdf"` (regex-validated)
**Response 201:** `JobResponse` with `status: "PENDING"`, `priority: "HIGH" | "STANDARD"`, no `result_url` yet, `attempts: 0`.
**Side effects:** writes a `PENDING` row to DynamoDB, sends an SQS message to `jobs-high` if `report_type ∈ {audit, executive_summary}` else `jobs-standard`.

### `GET /jobs/{job_id}` (auth required)
**Response 200:** `JobResponse`. If status is `COMPLETED`, `result_url` is a **presigned S3 URL valid for 15 minutes** (re-signed on every read).
**Errors:** 404 for both "not found" and "belongs to another user" (intentional — no enumeration).

### `GET /jobs?limit=20&cursor=...` (auth required)
**Query params:** `limit` (1–100, default 20), `cursor` (opaque string from previous response).
**Response 200:** `{ "items": [Job, ...], "next_cursor": str | null }` — cursor-based pagination over a DynamoDB GSI by `user_id` + `created_at` desc.

### `GET /events/me?token=<JWT>` (SSE stream)
**Why query-string token:** the browser `EventSource` API cannot set custom headers. Documented as a minor security limitation in `TECHNICAL_DOCS.md`.
**Response:** `text/event-stream`. Pushes `event: job-update` payloads `{ event, job_id, user_id, status, result_url, error, updated_at }` whenever the worker publishes to Redis. A keepalive comment is sent every 15s; ALB idle timeout is 60s.

### `GET /health`
Public. Returns `{ "status": "ok" | "degraded", "checks": { dynamodb, sqs, redis, s3 }, "version": "<git_sha>" }`.

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
