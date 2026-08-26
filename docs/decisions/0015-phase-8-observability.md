# ADR 0015: Observability, Prometheus metrics (Phase 8)

- Status: Accepted
- Date: 2026-07-18
- Decision owners: Aswani and the project orchestrator

## Context

`MASTER-PLAN.md` lists observability as a v1 gate: OpenTelemetry spans per stage plus a
Prometheus `/metrics` endpoint (request count, stage latency, provider timeout rate, token
and cost counters). The plan's slippage cut order explicitly allows **"OTel spans →
Prometheus-only"** under time pressure. The service already exposes an open `/health` route
and a framework-independent worker whose stages are the natural instrumentation points.

## Decision

### 1. Prometheus-only, and dependency-free

Implement Prometheus text-exposition metrics and defer OpenTelemetry spans (per the cut
order). Do **not** add `prometheus-client` or an OTel SDK. Instead, a small standard-library
`observability` package provides a thread-safe `MetricsRegistry` of `Counter` and `Histogram`
instruments and renders the Prometheus text exposition format directly.

Rationale: the project keeps a deliberately minimal dependency surface (the domain is
stdlib-only). The exposed metric set is small and bounded, so a hand-rolled, well-tested
renderer is lower-risk than a new runtime dependency (no approval, no network, CI stays
trivially hermetic). Histogram buckets are cumulative with `_sum`/`_count` and an `+Inf`
bucket, matching the Prometheus contract.

### 2. The metric set (no tenant or PII labels)

Recorded by the worker into an injected registry:

- `iec_worker_jobs_total{outcome}`, succeeded / failed / retried / cancelled.
- `iec_worker_stage_duration_seconds{stage}`, histogram over `telemetry_load`, `baseline`,
  `llm_propose`, `verify`, `persist`.
- `iec_provider_timeouts_total`, LLM provider deadline hits.
- `iec_llm_tokens_total{kind}`, prompt / completion tokens (when the provider reports them).
- `iec_investigation_verdicts_total{verdict}`, supported / refuted / unknown.

Labels are low-cardinality and carry **no tenant, incident, run, signal, or model-text
values**, so the metrics surface leaks nothing sensitive.

### 3. Injection, not globals

The `Worker` takes an optional `metrics: MetricsRegistry` (default: a private, unshared
registry so the worker is fully functional when metrics are not scraped). A deployment shares
one registry between the worker and the control plane. The control plane's `create_app`
likewise takes an optional `metrics` registry.

### 4. An open `GET /metrics` endpoint

The control plane exposes `GET /metrics` (unauthenticated, like `/health`) rendering the
registry as `text/plain; version=0.0.4`. Because the metric set has no tenant/PII labels this
is safe; deployments should still restrict network access to the scrape endpoint. This is the
second open route (`/health` being the first); all data routes remain authenticated and
tenant-scoped.

### 5. No new dependency; phase-aware governance

`pyproject.toml`/`uv.lock` are unchanged. The validator extends to Phase 8 with the new
required files; the CI command set and pinned dependencies are unchanged.

## Consequences

### Positive

- Stage p50/p95 latency, provider-timeout rate, token usage, and verdict distribution are
  observable during an evaluation rerun with zero new dependencies.
- Instrumentation is injected and framework-independent; the domain is untouched.

### Cost / limitations

- **OpenTelemetry spans are deferred** (cut order); there is no distributed tracing yet.
- Metrics are in-process and reset on restart; there is no push gateway or exemplar support.
- Estimated **cost** is not computed here (only token counts); a price table is future work.

## Rejected alternatives

- **Add `prometheus-client`**, a new runtime dependency for a small, bounded metric set;
  rejected in favor of the stdlib renderer to preserve the minimal-dependency stance.
- **Tenant-labelled metrics**, high cardinality and a leakage risk; rejected.
- **Authenticate `/metrics`**, non-standard for scrapers and unnecessary given label-free
  metrics; network restriction is the deployment-time control instead.
