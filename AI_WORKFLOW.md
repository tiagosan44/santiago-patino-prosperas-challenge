# AI Workflow

This project was built with **Claude Code (Opus 4.7)** as the primary coding assistant. IntelliJ IDEA was used for navigation and review; no other AI tools were involved in code generation. This file is an honest account of what the workflow looked like in practice.

## How I worked

I leaned heavily on the `superpowers:brainstorming` workflow before writing any code. The Socratic back-and-forth forced me to commit to architectural decisions explicitly instead of letting the model default to whatever felt easiest. The choices that shape this project — DynamoDB multi-table, Fargate for the worker, SSE over WebSockets, Redis as a shared coordination layer — were all mine, defended out loud during brainstorming before a single file was created.

For implementation I used two modes:

- **Spec-driven** for architecture and module boundaries, where the criteria were already well-defined and writing them down up front was faster than iterating.
- **TDD** for individual modules where the contract was clear, especially in the worker (concurrency, retries, breaker state).

I routinely asked Claude to question its own output before I accepted it, with explicit focus on edge cases, integration tests, performance, and security. When a diff looked off, my first ask was always *"explain why this works"* before *"fix it"* — the explanation usually surfaced the real bug, and acceptance without explanation was the single biggest source of regressions when I let it slide.

## A correction worth flagging

The first attempt at the circuit breaker (bonus B2) was an in-memory `dict` scoped to one worker process. It would have passed unit tests and silently failed under any real deployment — two worker replicas each holding their own breaker state, never agreeing on whether a report type was OPEN. I caught this during review and asked Claude to migrate it to Redis with atomic `MULTI`/`EXEC` transactions. That same decision paid off twice more: Redis also became the pub/sub backbone for SSE fan-out across multiple API replicas (bonus B3), and the coordination layer that lets one replica notify another about job state changes. Without that correction, both B2 and B3 would break the moment ECS scaled past one container.

## What was deliberately not AI-driven

The decision to use **SSE instead of WebSockets** for bonus B3 was a manual call to save time. The spec asks for *"WebSockets or another mechanism"* to replace polling; SSE qualifies — the server proactively pushes events, and the browser's `EventSource` API handles reconnection automatically. I accepted the trade-offs explicitly (no client→server channel, JWT passed via query string instead of header) and documented them in `TECHNICAL_DOCS.md`.

The bonus selection itself was also a manual call based on time budget and risk: B1 (priority queues), B2 (circuit breaker), B4 (exponential back-off) and B6 (>70% coverage) fully implemented; B3 satisfied via SSE; B5 partially implemented via structured logging, CloudWatch metrics, and a `/health` endpoint that reports per-dependency status.

## Limitations I ran into

Two recurring frictions in AI-assisted infrastructure work:

1. **Terraform AWS provider drift.** The model occasionally generated HCL referencing attributes that exist in older versions of the AWS provider but were renamed or removed in 5.x. The fix was always the same — cross-check the resource against the provider registry before trusting the diff.
2. **Cross-file consistency on multi-module changes.** For changes that touched CloudFront + ALB + IAM together, the model would sometimes update one file and forget another. `terraform plan` + `git diff` caught these every time, but it meant I couldn't trust a *"this is done"* claim without verifying.

Neither was a blocker — both were addressed by reading every diff before accepting it, which is the workflow rule that made the rest of the project work.
