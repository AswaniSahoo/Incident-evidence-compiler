# Devlog 0009 — Phase 8: observability (Prometheus metrics)

Status: implemented on branch `phase/07-real-data` (continuing v1 hardening). Finalized with
verified evidence at acceptance.

## Goal

Make the pipeline observable during an evaluation rerun: per-stage latency, job outcomes,
provider-timeout rate, token usage, and verdict distribution, exposed on a Prometheus
`/metrics` endpoint — without adding a runtime dependency (ADR 0015).

## First principle

Add observability as behavior grows, but keep the dependency surface minimal and never let a
metrics label carry tenant, incident, run, signal, or model-text values.

## Smallest implemented slice

- `observability/metrics.py`: a thread-safe `MetricsRegistry` with `Counter` and `Histogram`
  (cumulative buckets, `_sum`/`_count`, `+Inf`) and a Prometheus text renderer — standard
  library only.
- `Worker` gains an injected `metrics` registry (default private/unshared) and records:
  `iec_worker_jobs_total{outcome}`, `iec_worker_stage_duration_seconds{stage}`,
  `iec_provider_timeouts_total`, `iec_llm_tokens_total{kind}`, and
  `iec_investigation_verdicts_total{verdict}`.
- `create_app` gains an optional shared `metrics` registry and an open `GET /metrics` route
  (`text/plain; version=0.0.4`), alongside `/health`. All data routes stay authenticated.

## Testing strategy

`tests/test_observability.py` covers the exposition format (counter series; cumulative
histogram buckets with `_sum`/`_count`/`+Inf`; idempotent registration; timer), that a
successful worker run records the outcome/verdict/stage metrics into a shared registry, that a
failed run records a `failed` outcome, and that the ASGI `/metrics` endpoint is open and
renders the registry. Fully hermetic — no network, database, or credentials.

## Verification

Hermetic gate green: `compileall`; unittest (with PostgreSQL and Gemini-live tests skipped);
`ruff check`; `ruff format --check`; strict `mypy`; `python scripts/validate_project.py`
(full) under Phase 8. No new runtime dependency; `pyproject.toml`/`uv.lock` unchanged.

## Limitations

OpenTelemetry spans are deferred per the ADR 0007 cut order (Prometheus-only). Metrics are
in-process and reset on restart. Estimated cost is not computed (only token counts).

## Next question

A runnable server entrypoint that wires a shared registry into both the control plane and the
worker under `uvicorn`, plus a container image and a docker-build CI gate (Phase 8 hardening,
Step 3 of the v1 ship plan).
