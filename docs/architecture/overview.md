# Architecture Overview

## Status

Target architecture only. Phase 0 contains no runtime implementation.

## Intended flow

```text
Authenticated client
        |
        v
Async FastAPI control plane
  - token validation
  - tenant/role policy
  - Redis admission control
  - transactional idempotent submission
        |
        v
PostgreSQL source of truth
  - investigations and jobs
  - attempts and cancellation
  - evidence and verifier traces
  - reports, lineage, and audit events
        |
        v
Async workers using leased at-least-once jobs
  - fixed bounded telemetry adapters
  - temporal evidence compiler
  - Gemini hypothesis proposal
  - deterministic tri-state verifier
  - strict report validation
        |
        v
OpenTelemetry traces and Prometheus metrics
```

## Trust boundaries

- Identity establishes tenant context; request bodies cannot choose it.
- PostgreSQL row-level security backs application authorization.
- Telemetry and runbooks are untrusted evidence.
- Gemini output is an untrusted proposal constrained by a schema and verifier.
- Only application-owned parameterized queries access data.
- Redis is disposable admission control, not authoritative state.
- A report is accepted only after local evidence and policy validation.

## Planned delivery semantics

The worker queue is initially PostgreSQL-backed with leases and `FOR UPDATE SKIP LOCKED`. Delivery is at least once. External calls may repeat after worker failure; stage/result commits must be idempotent and duplicate cost must remain observable.

## Deferred choices

Qdrant, reranking, result caching, SSE, cloud deployment, and a frontend require measured or user-facing justification.
