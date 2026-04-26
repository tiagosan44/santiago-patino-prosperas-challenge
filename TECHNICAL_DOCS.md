# Technical Documentation — Prosperas Full-Stack Challenge

> Long-form companion to [`README.md`](./README.md). Written for a senior engineer reviewer who wants to understand _why_ things were built this way, not just _what_ was built.

---

## 1. System overview

The system lets authenticated users submit report generation requests through a React frontend. Requests are queued in AWS SQS and picked up by an async worker pool that simulates report generation (5–30 seconds of compute). Results are persisted to S3. Users see job status change in real time through a persistent SSE connection — no polling, no page refresh.

The design centers on two explicit constraints: the reviewer must be able to run the full stack locally with a single command (`docker compose up`), and every bonus requirement (B1–B6) must be demonstrable from the UI without code changes. That combination drove most of the architectural choices described below.

The production deployment runs entirely on AWS and is brought up by pushing to `main`. GitHub Actions builds container images, applies Terraform, force-rolls the ECS services, and smoke-tests the health endpoint — all in one pipeline run.

The local development environment mirrors production as closely as possible. LocalStack provides in-process emulation of DynamoDB, SQS, S3, and SNS. An `init-aws` sidecar container runs on startup to create all the tables, queues, and buckets — no manual `aws configure` or CLI commands required. The same Docker images used in production run locally, so environment drift is minimal.

See [`docs/architecture.md`](./docs/architecture.md) for component and sequence diagrams.

The six bonus requirements (B1–B6) are all demonstrable without code changes: job priority routing (B1) is exercised by choosing `executive_summary` vs `sales` in the form; the circuit breaker (B2) opens after submitting several `force_failure` jobs in quick succession; SSE updates (B3) are visible in the dashboard without a page refresh; back-off (B4) is observable via the CloudWatch metric `circuit_breaker.opens` or the structured worker logs; observability (B5) is the `/health` endpoint and the CloudWatch namespace; test coverage (B6) is reported by pytest with `--cov`.

---

## 2. Component responsibilities

### API service (ECS Fargate, 2 replicas)

The FastAPI application runs under Uvicorn with two worker processes per container. It handles five concerns:

- **Authentication** — `POST /auth/login` validates credentials against the DynamoDB `users` table (bcrypt, cost 12), returns a short-lived JWT (HS256). All other endpoints require `Authorization: Bearer <token>`.
- **Job submission** — `POST /jobs` validates the request body with Pydantic v2, writes a `PENDING` item to DynamoDB with a `version=1` counter, then enqueues to the appropriate SQS queue based on `report_type`. Returns 201 immediately; the queue provides the decoupling.
- **Job listing and retrieval** — `GET /jobs` paginates with DynamoDB `LastEvaluatedKey` encoded as base64 cursor. `GET /jobs/{id}` returns the job including a presigned S3 URL (15-minute TTL) once `status=COMPLETED`.
- **Real-time events** — `GET /events/me` opens an SSE stream. Because `EventSource` doesn't support custom headers, the JWT is passed as a `?token=` query parameter (documented as a minor security limitation; in production it would be mitigated by short TTL + HTTPS-only). On startup, every API replica spawns a background task that subscribes to the Redis pub/sub channel `job-updates`. Incoming messages are matched by `user_id` against the in-process connection registry and forwarded to the correct stream.
- **Health** — `GET /health` performs live dependency checks (DynamoDB `describe_table`, SQS `get_queue_attributes`, S3 `head_bucket`, Redis `ping`) and returns structured JSON with `version` set to the git SHA injected at build time.

### Worker service (ECS Fargate, 2 replicas)

The worker is a pure asyncio application — no HTTP server, no FastAPI. On startup it launches `WORKER_CONCURRENCY` (default 4) asyncio tasks, each running a receive loop. Boto3 calls are wrapped in `asyncio.to_thread` to avoid blocking the event loop while waiting on SQS long-polling.

The receive loop prefers the high-priority queue (1-second wait time); if that returns empty it falls through to the standard queue (20-second long-poll). This polling cascade ensures `executive_summary` and `audit` jobs are never delayed behind a backlog of lower-priority work.

For each message the worker: checks the circuit breaker, transitions the job to `PROCESSING` (optimistic lock), executes the processor, writes the result to S3, transitions to `COMPLETED`, publishes a Redis event, and deletes the SQS message. Any exception triggers the back-off path described in section 6.

### Redis (ECS Fargate Spot, 1 replica)

Redis serves two unrelated purposes:

1. **Pub/sub fan-out** for SSE events — workers publish, all API replicas receive.
2. **Circuit breaker state** — a hash per `report_type` tracks `state`, `failure_count`, and `opened_at`. Because multiple worker containers share this state, Redis makes the breaker cluster-wide.

Redis runs on Fargate Spot (70% cheaper). Its state is ephemeral by design: if the Spot task is reclaimed, a new one starts, the breaker resets to CLOSED (safe default), and in-flight SSE connections reconnect via the `EventSource` auto-reconnect. The DNS name `redis.prosperas.local` is provided by AWS Cloud Map, so the IP change from a Spot replacement is transparent.

### DynamoDB

Two tables; see section 3 for the full data model. DynamoDB was chosen over RDS for three reasons: free-tier perpetual eligibility, no VPC endpoint cost for S3 and DynamoDB (gateway endpoints are free), and the access patterns (point lookups by primary key, range scans by user + time) map cleanly to the key-value model without joins.

### SQS (three queues)

`jobs-high` and `jobs-standard` both configure a redrive policy with `maxReceiveCount=3` pointing at `jobs-dlq`. Visibility timeout is 90 seconds — chosen to be comfortably longer than the maximum simulated processing time (30 s) plus some margin, while still allowing timely redelivery on crash.

### S3 (two buckets)

`prosperas-reports` stores job result JSON under `reports/{user_id}/{job_id}/result.json`. Objects are private; access is via presigned URLs generated at retrieval time. A lifecycle rule expires objects after 30 days. The frontend assets live in a separate private bucket accessed exclusively via CloudFront OAC (Origin Access Control) — direct S3 access returns 403.

The key path convention (`reports/{user_id}/{job_id}/result.json`) supports per-user prefix-level IAM policies, which would make it straightforward to add user-scoped access boundaries in a future hardening pass. Right now the IAM prefix scope is `reports/` (all users) rather than per-user, because the task role is shared; separating per-user prefixes would require per-user roles or an intermediate signing Lambda.

---

## 3. Data model

### `users` table

```
PK: user_id (UUID v4)
Attributes: username, password_hash (bcrypt), created_at (ISO 8601)
GSI: username-index (PK = username)
```

The GSI exists for login: looking up a user by `username` without it would require a table scan. The PK is a UUID because it's used as a foreign key in the `jobs` table — stable and opaque.

### `jobs` table

```
PK: job_id (UUID v4)
Attributes: user_id, status, report_type, priority, params (Map),
            result_url (S3 key, nullable), error (nullable), attempts,
            created_at, updated_at, version
GSI 1: user-created-index  (PK = user_id, SK = created_at)
GSI 2: status-created-index (PK = status, SK = created_at)
```

`user-created-index` drives `GET /jobs` — it returns a user's jobs sorted by creation time without touching items owned by other users. The sort key on `created_at` (ISO 8601 string) preserves lexicographic order, making cursor-based pagination straightforward.

`status-created-index` is used by the `/health` endpoint to count recent jobs per status as a lightweight operational metric. It's also available for backfill or admin queries without a scan.

`version` is the optimistic-locking counter. Every write that transitions status includes `ConditionExpression: version = :expected` and increments `version`. If two workers somehow receive the same message and race, the second `UpdateItem` fails with `ConditionalCheckFailedException` rather than silently overwriting. The losing worker retries after the SQS visibility timeout expires and, at that point, the DynamoDB item already reflects the correct terminal state — so the worker recognizes the job is done and deletes the message.

`attempts` tracks how many times the worker has touched this job. It's incremented on each `PROCESSING` transition and read by the circuit breaker to decide whether to open.

### SQS message format

The message body is a JSON envelope that carries enough information for the worker to process the job without making a DynamoDB read upfront:

```json
{
  "version": 1,
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "report_type": "sales",
  "params": { "date_range": "2026-01-01/2026-03-31", "format": "json" },
  "enqueued_at": "2026-04-26T14:00:00Z",
  "attempt": 1
}
```

`enqueued_at` lets the worker compute `queue.lag_seconds` at the moment it picks up the message, without querying SQS message attributes. `attempt` is informational; the authoritative attempt count is `attempts` in DynamoDB, which the worker increments atomically.

### Why multi-table instead of single-table?

Single-table DynamoDB design (access-pattern-first, heterogeneous item types) is powerful but imposes significant cognitive overhead during design and defense. With only two entity types and a small set of access patterns (lookup by user_id, lookup by job_id, list jobs by user), the win from multi-table is explicit, independently evolvable schemas and simpler reasoning. The cost is one extra table and one extra read when joining — neither of which matters at this scale.

### Pagination strategy

`GET /jobs` uses DynamoDB's native cursor-based pagination rather than offset-based. The `LastEvaluatedKey` from a `Query` call is base64-encoded and returned as `next_cursor`. The client passes it as `?cursor=<value>` on the next request, which the API decodes and passes as `ExclusiveStartKey`. This approach is O(1) in the number of items skipped (DynamoDB resumes from the cursor position internally) and doesn't suffer from the phantom-read or offset-drift problems that affect SQL OFFSET.

---

## 4. Job lifecycle and state machine

```
PENDING → PROCESSING → COMPLETED
                     ↘ FAILED
```

Transitions are enforced at the DynamoDB level via `ConditionExpression`, not just by convention in application code. This means a concurrent or duplicate worker cannot put a `COMPLETED` job back into `PROCESSING`.

The full lifecycle from user click to download:

1. User submits form → `POST /jobs` → DynamoDB `PENDING`, `version=1` → SQS message.
2. Worker receives SQS message → circuit breaker check → `UpdateItem` to `PROCESSING`, `version=2`, `attempts=1`.
3. Worker calls `processor.process()` → `asyncio.sleep(random 5–30s)` → returns result dict.
4. Worker calls `s3.put_object` → `UpdateItem` to `COMPLETED`, sets `result_url`, `version=3`.
5. Worker publishes `{job_id, user_id, status: COMPLETED, result_url}` to Redis channel.
6. All API replicas receive the Redis message → match `user_id` → push SSE event to open stream.
7. Frontend `EventSource` handler updates Zustand store → React re-renders the badge.
8. User clicks "Download" → `GET /jobs/{id}` → API generates presigned URL → browser fetches it directly from S3.

The SSE event carries the full status payload. The frontend applies it directly to the store without re-fetching, keeping the UI update latency to single-digit milliseconds after the worker publishes.

### Error state and retry hint

When a job reaches `FAILED`, the DynamoDB item contains an `error` field with a human-readable message (e.g., `"ProcessingError: downstream service unavailable"`). The API includes this in the `GET /jobs/{id}` response and in the SSE event payload. The frontend renders it as a tooltip on the red `FAILED` badge and shows a "Retry" button that pre-fills the job form with the same parameters. The retry creates a new job — there is no server-side retry mechanism beyond the automatic back-off on the original message.

---

## 5. Real-time updates: SSE + Redis pub/sub

### Why SSE instead of WebSockets

The communication here is strictly server-to-client: the server pushes status updates; the client never sends data over the same connection. SSE is the right primitive for this. It's simpler to implement, works over HTTP/1.1, reconnects automatically via `EventSource`, and requires no special proxy configuration.

WebSocket API Gateway was considered and rejected: it adds cost, requires connection management in DynamoDB or a shared store, and provides no benefit over SSE for a unidirectional use case.

### The multi-instance fan-out problem

With two API replicas, a worker's Redis publish must reach both replicas — otherwise a user connected to replica A won't see updates from a job processed while replica B is handling the event. The solution is straightforward: every API replica subscribes to the `job-updates` Redis channel on startup. When a worker publishes an event, all replicas receive it. Each replica checks its in-process map of `{user_id → [stream_response_objects]}` and forwards to matching connections.

The in-process connection map is ephemeral (lost on restart), but `EventSource` reconnects automatically. On reconnect the client fetches `GET /jobs` to re-hydrate the current state before re-opening the SSE stream, so no updates are permanently lost.

### Heartbeat

ALB has a default idle timeout of 60 seconds. An SSE connection with no traffic would be silently closed. The API sends a comment event (`: keepalive\n\n`) every 15 seconds over every open stream. This resets the idle timer without affecting the client — SSE comments are defined in the spec as ignored by consumers.

### JWT in SSE

Standard `EventSource` does not allow setting request headers. The JWT is passed as `?token=<jwt>` in the SSE URL. The API extracts and validates it identically to the `Authorization: Bearer` header path. The risk (token visible in server access logs) is mitigated by: short token TTL, HTTPS on the CloudFront path, and the fact that this is a demo without sensitive data. In a production hardening pass the token would be exchanged for a short-lived SSE ticket via a dedicated endpoint, keeping the JWT out of URLs entirely.

### Frontend SSE hook

The React `useJobEvents` hook wraps `EventSource` with three behaviors:

1. **Reconnect on error** — when the `EventSource` fires an `onerror` event, the hook waits 2 seconds and reopens the connection. The server assigns a new connection ID on reconnect.
2. **State re-hydration on reconnect** — on reconnect, the hook dispatches a `fetchJobs` action against the Zustand store, which calls `GET /jobs` and replaces the local state with the authoritative server state. This ensures events missed during the disconnection period are recovered.
3. **Cleanup on unmount** — the `useEffect` cleanup closes the `EventSource` and cancels the reconnect timer, preventing memory leaks when the user logs out or navigates away.

The hook is tested in `frontend/tests/hooks/useJobEvents.test.ts` using a mock `EventSource` that simulates message delivery and error conditions.

---

## 6. Resilience

### Visibility timeout and redelivery

SQS visibility timeout is set to 90 seconds. If a worker container crashes mid-processing, the message becomes visible again after 90 seconds and is picked up by another worker (or the same one after restart). The worker checks `attempts` in DynamoDB before processing — if the job is already `COMPLETED` or `FAILED`, it deletes the message and returns, preventing duplicate processing.

### Optimistic locking

Every `UpdateItem` includes `ConditionExpression: attribute_exists(job_id) AND #version = :expected_version`. This serializes concurrent writes at the DynamoDB level. A race between two workers on the same message results in one succeeding and the other receiving `ConditionalCheckFailedException`, which is caught and treated as a no-op — the message is deleted and the job is left in whatever terminal state the winner set.

### Exponential back-off (B4)

When `processor.process()` raises `ProcessingError`, the worker does not let the message become visible via the natural timeout. Instead it calls `change_message_visibility` with a calculated delay:

```
delay = min(900, 90 * 2 ** (attempt - 1))
# attempt=1: 90s, attempt=2: 180s, attempt=3: 360s (capped at 900s)
```

This implements true exponential back-off on top of SQS's otherwise flat redelivery model. The benefit is that a dependency outage (e.g., S3 temporarily unavailable) doesn't flood the queue with rapid-fire retries.

On the third attempt the worker marks the job `FAILED` in DynamoDB (with the error message), publishes a `FAILED` event to Redis, and deletes the message from SQS. The job is terminal in the application's state machine even though SQS's `maxReceiveCount` has not yet been exceeded — the message is explicitly deleted so it doesn't end up in the DLQ unnecessarily.

The DLQ still serves as a safety net for messages that the worker drops entirely (container OOM kill, network partition during delete, etc.).

### Circuit breaker (B2)

The circuit breaker is keyed by `report_type`. State is stored in Redis as a hash `circuit_breakers:{report_type}` with fields `state` (CLOSED/OPEN/HALF_OPEN), `failure_count`, and `opened_at`.

Transitions:
- **CLOSED → OPEN**: `failure_count` reaches 3. The breaker opens for 60 seconds.
- **OPEN**: all incoming jobs of that report type are rejected immediately (job transitions directly to `FAILED` with `CircuitBreakerOpenError`). This prevents workers from spending time on jobs that will certainly fail.
- **OPEN → HALF_OPEN**: after the 60-second recovery window, the next job is allowed through.
- **HALF_OPEN → CLOSED**: if the probe job succeeds, `failure_count` resets.
- **HALF_OPEN → OPEN**: if the probe job fails, the breaker reopens.

State transitions are atomic via a Lua script executed in a single Redis round-trip, preventing race conditions when multiple worker tasks run concurrently. The Lua approach was chosen over Redis transactions (`MULTI/EXEC`) because it's a single network call regardless of field count.

### Dead letter queue and alarms

The DLQ `jobs-dlq` receives messages after 3 failed receive attempts from either priority queue. A CloudWatch alarm fires when `NumberOfMessagesVisible > 0` for 5 consecutive minutes, sending a notification via SNS email. This is the on-call signal that something systematic is failing.

---

## 7. Concurrency model

The worker is built entirely on Python's `asyncio`. There is no threading except where explicitly bridged.

`WORKER_CONCURRENCY` asyncio tasks run inside a single event loop within a single container. Each task runs an independent receive loop — they do not share state beyond the circuit breaker (which is in Redis, external to the process).

Boto3 is synchronous; all boto3 calls that block on I/O (`receive_message`, `put_object`, `update_item`, etc.) are dispatched to the default `ThreadPoolExecutor` via `asyncio.to_thread`. This allows the event loop to continue handling other tasks while a slow S3 upload completes. The processor's `asyncio.sleep` calls yield control naturally without blocking.

The result is that 2 worker replicas × 4 concurrent tasks = 8 messages being processed in parallel at steady state. For the 5–30s simulated work, this is more than enough throughput.

The `asyncio.to_thread` pattern was chosen over `aiohttp` or `aiobotocore` because it requires zero library changes and the per-thread overhead (one thread per in-flight boto3 call) is negligible at this concurrency level.

### Graceful shutdown

The worker's `main.py` registers a `SIGTERM` handler (sent by ECS during task replacement) that sets a cancellation flag. Each receive loop checks the flag at the top of its iteration before calling `receive_message`. In-flight messages continue to their natural completion or back-off. Tasks that are mid-`asyncio.sleep` in the processor are cancelled via `Task.cancel()` after a 10-second drain period; the corresponding SQS messages become visible again via the visibility timeout, not the DLQ, so no processing credit is wasted.

### Resource limits

ECS task definitions set hard limits: API containers get 512 MiB RAM and 0.5 vCPU (soft); worker containers get 1 GiB RAM and 1 vCPU to accommodate the thread pool. CPU and memory are the primary auto-scaling signals for the API service. Workers scale on SQS queue depth rather than CPU, because the bottleneck is I/O wait on S3 and DynamoDB, not CPU.

---

## 8. Observability

### Structured logging

Every log line is JSON, emitted by `structlog`. Fixed fields on every line: `timestamp`, `level`, `service` (either `api` or `worker`), `request_id` (UUID injected by middleware on the API side), `event`. Request-scoped fields (`user_id`, `job_id`) are bound to the `structlog` context at the start of each request and flow through all subsequent log calls in that context automatically.

Logs go to stdout, collected by the ECS `awslogs` driver, and shipped to CloudWatch Logs (`/ecs/prosperas/api` and `/ecs/prosperas/worker`). Retention is set to 7 days.

### Custom CloudWatch metrics

The worker and API publish to a `Prosperas` namespace with the following metrics:

| Metric | Type | Dimensions |
|---|---|---|
| `jobs.created` | Counter | `report_type` |
| `jobs.completed` | Counter | `report_type`, `priority` |
| `jobs.failed` | Counter | `report_type`, `error_type` |
| `jobs.processing_duration_seconds` | Histogram | `report_type` |
| `queue.lag_seconds` | Gauge | — |
| `circuit_breaker.opens` | Counter | `report_type` |

`queue.lag_seconds` is computed by the worker as the difference between the current time and `enqueued_at` from the SQS message body. This gives a direct measure of consumer lag independent of the SQS `ApproximateAgeOfOldestMessage` attribute, which has a 1-minute resolution.

### `/health` endpoint

`GET /health` returns a 200 with dependency statuses on a live check, or a 503 if any dependency is unhealthy:

```json
{
  "status": "healthy",
  "deps": {
    "dynamodb": "healthy",
    "sqs_high": "healthy",
    "sqs_standard": "healthy",
    "s3": "healthy",
    "redis": "healthy"
  },
  "version": "a3f9c12"
}
```

`version` is the git SHA passed as an environment variable by the ECS task definition, set by the deploy workflow. The smoke test in CI hits this endpoint after every deploy.

### Alarms

Three CloudWatch alarms are configured via the `observability` Terraform module:

- `dlq_not_empty`: triggers when the DLQ has visible messages for 5 consecutive minutes.
- `api_5xx_high`: triggers when the 5xx error rate on the ALB target group exceeds 1% over 5 minutes.
- `worker_lag_high`: triggers when `queue.lag_seconds` P95 exceeds 60 seconds over 5 minutes.

All alarms notify an SNS topic that fans out to an email subscription.

### Error handling and response format

The API uses FastAPI's `exception_handler` decorator to catch both application-defined exceptions (e.g., `JobNotFoundError`, `UnauthorizedError`) and unhandled exceptions. All error responses follow a consistent envelope:

```json
{
  "error_code": "JOB_NOT_FOUND",
  "message": "Job 550e8400 not found or not owned by current user",
  "request_id": "d4e8f1a2-..."
}
```

`request_id` is generated by middleware at request ingress and injected into both the response body and the `X-Request-ID` response header. It's also bound to the `structlog` context, so every log line for a request carries the same ID. This makes it straightforward to pull all logs for a specific failed request from CloudWatch Insights with `filter @message like "d4e8f1a2"`.

Pydantic v2 validation errors from request bodies are caught by FastAPI's built-in handler and return 422 with a structured list of field-level violations. These are not logged at ERROR level (they are expected client mistakes), only at DEBUG to avoid alarm noise.

---

## 9. Security

### IAM least-privilege

Three IAM roles are created by the `iam` Terraform module:

- **`prosperas-api-task-role`**: `sqs:SendMessage` on the two standard queues (not the DLQ), `dynamodb:Query/PutItem/UpdateItem/GetItem` on both tables scoped to specific table ARNs, `s3:GetObject` on the reports bucket (prefix `reports/` only), `sns:Subscribe` on the topic ARN.
- **`prosperas-worker-task-role`**: `sqs:ReceiveMessage/DeleteMessage/ChangeMessageVisibility` on all three queue ARNs, `dynamodb:UpdateItem/GetItem` on the jobs table, `s3:PutObject` on the reports bucket (prefix `reports/` only), `sns:Publish` on the topic ARN.
- **`prosperas-ecs-task-execution-role`**: ECR `GetAuthorizationToken` + `BatchGetImage` + `GetDownloadUrlForLayer`, CloudWatch Logs `CreateLogStream` + `PutLogEvents`.

The API task role deliberately lacks `s3:PutObject` (it doesn't write reports) and the worker task role lacks `sqs:SendMessage` (it doesn't enqueue new jobs). Both lack DynamoDB `DeleteItem` and `Scan`.

### JWT

Tokens are HS256-signed with a secret stored in GitHub Secrets and injected into ECS as an environment variable via AWS Secrets Manager references in the task definition. Token expiry is set to 60 minutes. There is no refresh token mechanism in this implementation (explicitly out of scope).

### Encryption at rest

DynamoDB tables use AWS-managed KMS keys (SSE enabled, default). S3 buckets use SSE-S3 (AES-256). These are the default configurations; no additional cost.

### Network

All ECS tasks run in private subnets with no public IP. The only public-facing resources are the ALB (port 80, HTTP for the demo) and CloudFront (HTTPS, port 443). VPC gateway endpoints for S3 and DynamoDB keep that traffic off the public internet and avoid NAT charges for those services.

The `force_failure` report type (the demo hook for the FAILED state) is not an admin backdoor — it's just a report type that the processor is hard-coded to fail on. Any authenticated user can submit it; it doesn't bypass authorization or expose sensitive behavior.

### CORS

The FastAPI app configures `CORSMiddleware` with an explicit `allow_origins` list. In production this is set to the CloudFront distribution URL only. Locally it includes `http://localhost:5173`. The configuration is environment-variable-driven so the same image works in both contexts without rebuild.

Preflight requests (`OPTIONS`) are handled by the middleware before they reach any route handler. The allowed headers include `Authorization` and `Content-Type`; exposed headers include `X-Request-ID` so the frontend can log the request ID alongside client-side error reports.

### Pre-commit secrets scanning

A `gitleaks` pre-commit hook runs on every commit. It's configured to catch AWS access keys, JWT secrets, and generic high-entropy strings. The `.env` file is gitignored; the `.env.example` contains only placeholder values. The CI pipeline also runs `gitleaks` as an independent step before any AWS credentials are loaded, providing a second line of defense.

---

## 10. Infrastructure

### VPC layout

`10.0.0.0/16` in `us-east-1`. Two public subnets (`/24`) in `us-east-1a` and `us-east-1b` host the ALB and one NAT Gateway (in `1a` only). Two private subnets (`/24`) in the same AZs host all ECS tasks. Traffic from private subnets to the internet (ECR image pulls, CloudWatch Logs, SQS/SNS calls not covered by gateway endpoints) goes through the single NAT Gateway.

The single NAT Gateway is a deliberate cost trade-off: a redundant NAT in `1b` would cost ~$30/month additional and provide resilience only if `1a` itself fails, which AWS SLA puts at an extremely low probability. For a demo deployment, this is acceptable. See section 11.

### ECS cluster and services

All three services (api, worker, redis) run on the same ECS cluster. Task definitions pin the image to the ECR tag pushed by the current deploy (`:<git-sha>`). The `latest` tag is also pushed so Terraform doesn't need to know the SHA for initial provisioning.

Auto-scaling is configured for `api` (CPU > 70%, min 2 / max 4) and `worker` (SQS `ApproximateNumberOfMessagesVisible / desired_count > 10`, min 2 / max 8). Redis does not scale.

### Cloud Map

A private DNS namespace `prosperas.local` in the VPC provides service discovery. Each ECS service registers its tasks under a hostname (`api.prosperas.local`, `worker.prosperas.local`, `redis.prosperas.local`). The API connects to Redis via `redis://redis.prosperas.local:6379/0`. When a Fargate Spot replacement spawns a new redis task with a different IP, Cloud Map updates the A record and the API reconnects automatically on the next `ping` failure.

### Terraform state

Remote state lives in an S3 bucket (`prosperas-tfstate`) with versioning enabled. Locks are held in a DynamoDB table (`prosperas-tflock`). The backend configuration is in `infra/terraform/environments/prod/backend.tf`. The S3 bucket and DynamoDB table must be created manually before the first `terraform init` — they are bootstrapped by a one-time script rather than managed by Terraform itself (to avoid the chicken-and-egg problem).

### CI/CD pipeline structure

Two workflows cover the full development lifecycle:

**`pr.yml`** — triggered on pull requests to `main`. Runs in parallel: backend lint (ruff), frontend lint (ESLint), backend unit tests (moto, no LocalStack), frontend unit tests (Vitest). Then sequentially: backend integration tests (LocalStack sidecar in the GitHub runner), `terraform validate` + `terraform plan`. The plan output is posted as a PR comment via the `hashicorp/terraform-github-actions` provider.

**`deploy.yml`** — triggered on push to `main`. Extends `pr.yml` with: build API and worker Docker images (tagged with both the git SHA and `latest`), push to ECR, `terraform apply` (idempotent — creates or updates resources), update ECS service task definitions to the new image SHA, `ecs wait services-stable` (5-minute timeout), build the frontend Vite bundle with the real ALB URL injected as `VITE_API_URL`, sync to the frontend S3 bucket, CloudFront invalidation on `/*`, curl the `/health` endpoint with 5 retries and 10-second backoff, and finally print the CloudFront and ALB URLs as a workflow summary.

The workflow uses `aws-actions/configure-aws-credentials` with short-lived OIDC tokens where possible (for environments that support it) and falls back to access key + secret for the initial bootstrap.

### Module design

The 11 Terraform modules follow a pattern of thin wrappers: each module accepts the minimum set of input variables needed to construct its resources, outputs ARNs and names for consumption by dependent modules, and avoids internal `data` source lookups (keeping plans deterministic and fast). The composition root in `environments/prod/main.tf` wires them together, passing outputs from `network` to `ecs`, `ecs` to `alb`, etc.

This separation means each module can be `terraform plan`'d in isolation with a stub variable file during development, without needing a full account bootstrap. It also makes the module boundaries easy to review: `modules/iam/` is the authoritative location for all IAM role definitions, `modules/observability/` for all alarms and log groups.

---

## 11. Testing strategy

### Backend: three-layer test pyramid

**Unit tests** (`backend/tests/unit/`) use `moto` to mock DynamoDB, SQS, and S3 in-process. Boto3 picks up moto's mock endpoints automatically when the `@mock_aws` decorator is applied. These tests are fast (no network, no Docker) and cover individual service functions, Pydantic model validation, JWT encoding/decoding, and worker logic branches (back-off calculation, circuit breaker state transitions, optimistic lock conflict handling).

**Integration tests** (`backend/tests/integration/`) spin up LocalStack as a Docker sidecar in the GitHub Actions runner (or locally via `docker compose`). The full FastAPI app is instantiated in-process against real LocalStack endpoints. These tests exercise complete HTTP flows: POST a job, verify DynamoDB state, assert the SQS message body, simulate the worker consuming it, assert the final DynamoDB state and the Redis pub/sub payload.

The critical integration test for resilience: inject a failure in the processor mock, assert that `change_message_visibility` is called with exponentially increasing delays, assert the DLQ receives the message after the redrive threshold is exceeded, and assert the job's `status` is `FAILED` in DynamoDB.

**Coverage enforcement**: `pyproject.toml` sets `fail_under = 70`. The current run achieves 86%, with most of the gap in SSE connection lifecycle edge cases (browser disconnect mid-stream) that are difficult to test without a real HTTP connection.

### Frontend: unit and E2E

**Unit tests** (`frontend/tests/*.test.ts`) use Vitest + Testing Library. They cover:
- `JobForm` — form submission, validation error display, disabled state while submitting.
- `JobList` — rendering a list of jobs with correct badge colors, empty state.
- `StatusBadge` — correct color and label per status value.
- `useJobs` hook — pagination, error handling, optimistic status update on SSE event.
- Zustand store reducers — `applyJobEvent` correctly merges incoming SSE payload into existing job list.

**E2E tests** (`frontend/tests/e2e/`) use Playwright against the full local stack. The suite is headless (Chromium) and covers:
- Happy path: login → submit job → observe badge transition PENDING → PROCESSING → COMPLETED (via SSE) → click download → file arrives.
- Failure path: submit `force_failure` job type → observe FAILED badge with error tooltip.
- Auth guard: navigating to the dashboard without a token redirects to login.
- Session persistence: refreshing the page preserves the job list (Zustand store is re-hydrated from `GET /jobs`).

The E2E suite uses `page.waitForSelector` with generous timeouts (30s) to accommodate the 5–30s simulated processing time. Tests are tagged `@slow` so they can be excluded from fast PR feedback loops when needed.

### Test isolation

All tests are designed to be order-independent. Unit tests use fresh moto contexts per test function. Integration tests generate unique table/queue names per test run via a UUID suffix, so parallel test runs on the same LocalStack instance don't interfere. The Playwright tests use a dedicated test user (`test_e2e_<uuid>`) created at the start of each suite run and cleaned up afterward.

---

## 12. Trade-offs and limitations

The following limitations are intentional, not oversights:

| Limitation | Reason | Production fix |
|---|---|---|
| Single NAT Gateway (1 AZ) | Saves ~$30/mo for a demo | Add second NAT in 1b; ~1h Terraform change |
| HTTP-only ALB | No domain → no ACM cert | Add Route 53 hosted zone + ACM cert + HTTPS listener |
| JWT query param on SSE endpoint | `EventSource` limitation | Exchange for short-lived SSE ticket via dedicated endpoint |
| No JWT refresh tokens | Out of scope for the challenge | Add a `POST /auth/refresh` endpoint with a refresh token table in DynamoDB |
| Redis state is ephemeral | Fargate Spot can be reclaimed | Switch to ElastiCache Serverless for persistent pub/sub state |
| No rate limiting | Out of scope | Add an API Gateway in front of the ALB, or implement token bucket per user in Redis |
| No distributed tracing | Out of scope | Integrate AWS X-Ray or OpenTelemetry |
| CloudFront → ALB is HTTP | No domain for ACM | Covered above; add HTTPS termination at ALB with a certificate |
| `prosperas-ci` IAM user has AdministratorAccess | Bootstrap simplicity | Scope to minimum required permissions once the resource ARNs are known |
| Simulated processing (sleep) | This is a demo | Replace `asyncio.sleep` in `processor.py` with real data pipeline logic |
| No API versioning prefix | Premature at challenge scope | Add `/api/v1/` prefix; add to section 13 |
| No password length/complexity policy | Out of scope | Enforce at Pydantic model layer before bcrypt |
| DLQ messages require manual inspection | Out of scope | Add Lambda trigger on DLQ for automated remediation or alerting |
| CloudFront invalidates `/*` on every deploy | Simplicity | Cache-bust only `index.html`; hash-named assets get long max-age |

---

## 13. What I would do differently for production at scale

**Multi-region active-passive.** The current deployment is single-region (`us-east-1`). For a real product, DynamoDB global tables + Route 53 latency routing to a standby region in `eu-west-1` would give sub-100ms failover RTO.

**Distributed tracing.** Structured logs are searchable but traces across API → SQS → Worker are invisible. Integrating AWS X-Ray (or OpenTelemetry with an ADOT sidecar) would give end-to-end latency histograms per `report_type` and surface slow P99 paths without log mining.

**ElastiCache Serverless for Redis.** The current Fargate Spot Redis is ephemeral. ElastiCache Serverless provides persistence, replication, and automatic failover at a cost-per-GB model that starts lower than a fixed node for light traffic. The circuit breaker state and SSE pub/sub would survive container replacements.

**Dead letter queue automation.** Currently DLQ messages are visible in CloudWatch alarms but require manual inspection and requeue. A Lambda triggered by the DLQ could attempt automated remediation (retry with a different queue, alert on-call with message context, or write a structured incident to a table).

**Secrets rotation.** The `JWT_SECRET` is a static value in GitHub Secrets. For production, it would be stored in AWS Secrets Manager with automatic rotation every 90 days, and the API would fetch it on startup (or use Secrets Manager's ECS integration for automatic injection on task definition update).

**Frontend CDN cache strategy.** The current CloudFront distribution invalidates `/*` on every deploy. This is simple but blunt. In production, assets with content hashes (the default Vite output) would get long `max-age` headers and only the `index.html` would be invalidated — reducing both invalidation costs and user-visible cache misses.

**Observability completeness.** The `queue.lag_seconds` metric is an approximation (based on message body timestamp). For precise lag measurement, SQS `SentTimestamp` message attribute should be used. Additionally, the worker currently doesn't emit a metric for circuit breaker `HALF_OPEN → OPEN` transitions (re-opening after probe failure) — worth adding to detect flapping.

**Testing coverage gaps.** The 86% coverage figure excludes some error paths in the SSE reconnect logic and the Terraform module `outputs.tf` validation. Adding contract tests between the API response schema and the frontend TypeScript types (e.g., via `openapi-ts` + `zod` code generation from the FastAPI OpenAPI schema) would catch breaking API changes before they reach E2E tests.

**Job cancellation.** There's no `DELETE /jobs/{id}` endpoint. A user who submits a job and immediately wants to cancel it has to wait for the processing cycle to complete. Adding optimistic cancellation (transition to `CANCELLED` in DynamoDB; the worker checks for `CANCELLED` before starting and skips) is a small addition that materially improves the user experience for long-running jobs.

**Horizontal worker scaling granularity.** The auto-scaling trigger is `ApproximateNumberOfMessagesVisible / desired_count > 10`. This fires a new ECS task (which has a cold-start of ~30 seconds on Fargate). For bursty workloads, a better approach is to pre-warm the worker pool and use the SQS `ApproximateNumberOfMessagesNotVisible` attribute as a secondary scaling input to account for in-flight messages. The current implementation is sufficient for the challenge but would need tuning in production.

**No backpressure from worker to API.** If the worker pool is fully saturated, the API continues accepting `POST /jobs` and enqueuing to SQS. SQS has a per-account soft limit of 120,000 in-flight messages per standard queue. At the simulated 5–30s processing time and 8 concurrent tasks, saturation is not a real concern. In production with real processing, the API could check the SQS `ApproximateNumberOfMessagesVisible` count on the queues and return 503 with a `Retry-After` header when the backlog exceeds a threshold.

**Frontend bundle size.** The Vite build is not analyzed in CI. Adding `rollup-plugin-visualizer` or `vite-bundle-analyzer` to the build step would surface any accidentally large dependencies. The current bundle is small (React, Tailwind, Zustand, react-hook-form, zod), but this check would prevent regressions.

**Password policy.** The `create_user` service function accepts any non-empty password. For a production system, minimum length and complexity requirements should be enforced at the Pydantic model layer before bcrypt hashing. Bcrypt has quadratic cost with password length past ~72 bytes (it silently truncates); enforcing a maximum length of 72 characters at the API boundary prevents a denial-of-service via extremely long password strings.

**API versioning.** The API has no versioning (`/v1/` prefix or `Accept: application/vnd.api+json;version=1` header). Any breaking change to the response schema would require a coordinated frontend and backend deploy. Adding an `/api/v1/` prefix to all routes from the start costs nothing and avoids a forced migration later.

**Audit log.** There is no append-only audit trail of job state transitions. In a production system with compliance requirements, every `UpdateItem` that changes `status` should also write a record to a separate `job_events` table (PK = `job_id`, SK = `timestamp`) capturing who triggered the transition and from which replica. DynamoDB Streams could feed this as an alternative to synchronous writes.

**Cost visibility.** The Terraform configuration does not include AWS Cost Allocation Tags on all resources. Adding `terraform apply` tags (`Project = prosperas`, `Environment = prod`, `Owner = <email>`) to all taggable resources would let AWS Cost Explorer break down spending by component, which is essential for production cost governance and identifying unexpected spikes.

---

_This document covers the implementation as of the challenge submission date. Architecture decisions and their trade-offs are intended to reflect the reasoning a candidate would articulate in a technical defense interview, not a production post-mortem. Feedback and questions welcome._
