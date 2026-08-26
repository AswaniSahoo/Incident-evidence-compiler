# Devlog 0007, Phase 6: control plane and worker

Status: implemented on branch `phase/06-control-plane` (not yet merged). Finalized with
verified evidence at acceptance.

## Goal

Turn the persistence (Phase 4) and LLM (Phase 5) boundaries into a runnable service: an
async control plane that accepts investigations and a worker that compiles telemetry into a
verified, replayable report (ADR 0013).

## Slices

- 6a (no dependency): a framework-independent `application` package, `CreateInvestigation`,
  `GetInvestigationStatus`, `GetReport`, and the `Worker` loop, depending only on the
  persistence/LLM ports plus a new `TelemetrySource` port (in-memory fake here; a durable
  RCAEval-backed source arrives in Phase 7). The worker: RUNNING → load telemetry → baseline
  → compile ledger → LLM propose → parse (untrusted) → verify → persist one content-addressed
  evidence row per ledger entry + one verification report → SUCCEEDED. Per-attempt deadline;
  provider errors retried then terminal; untrusted-output/domain failures terminal recording
  only a stable `error_code`; cancellation short-circuits. Additive touches: a per-entry
  `metric_evidence_entry_json` serializer, an `incident` field on `HypothesisRequest`, and a
  typed `FakeLLMClient` exhaustion error.
- 6b (adds `fastapi==0.139.2` + `uvicorn[standard]==0.51.0`): a FastAPI control plane,
  `POST /investigations` (202 + id, `Idempotency-Key`), `GET /investigations/{id}`,
  `GET /investigations/{id}/report`, and an open `GET /health`. Bearer-token auth maps a
  token to a tenant; every data route is authenticated and tenant-scoped, and cross-tenant
  reads return 404. Governance is phase-aware for Phase 6; Phases 1–5 are unchanged.

## Testing strategy

The hermetic gate exercises the full pipeline on the in-memory fakes + FakeLLMClient + fake
telemetry, including an end-to-end create→run→report and a stalled-model deadline test. The
control plane is driven in-process via `httpx.ASGITransport`: auth required, end-to-end
report, cross-tenant 404, not-ready 409, invalid-window 422, and `/health` staying
responsive while a worker coroutine is stalled. No server, database, network, or
credentials are needed.

## Verification note

Hermetic gate green (ruff/format/mypy, unittest, validate full pass under Phase 6,
`uv sync --locked`). The worker runs against the in-memory persistence fake; an end-to-end
run over real PostgreSQL and a real Gemini call remain opt-in and are not part of the gate.
