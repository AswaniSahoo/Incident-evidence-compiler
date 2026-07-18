# ADR 0013: Control plane and worker boundary (Phase 6)

- Status: Accepted
- Date: 2026-07-18
- Decision owners: Aswani and the project orchestrator

## Context

Phases 4 and 5 delivered the persistence boundary (repositories + `SKIP LOCKED` queue) and
the LLM provider boundary (async `LLMClient`, `FakeLLMClient`, untrusted parser). Phase 6
ties them to the deterministic domain in a runnable service: an async control plane that
accepts investigations and a worker that turns telemetry into a verified, replayable report.

Research against the current tree (branch `phase/06-control-plane`) confirmed the exact
integration surface and surfaced decisions this ADR must resolve before implementation:

1. **Telemetry-ingestion gap (largest).** Persistence stores no raw metric signals; a
   claimed job yields tenant/incident/run/window but no telemetry. The source of the
   `MetricSignal`s a job analyzes is undefined.
2. **Evidence-persistence granularity.** `EvidenceRecord` is content-addressed per
   `evidence_id`, but the only serializer is `ledger_json` (whole ledger); there is no
   per-entry serializer and no ledger-level id.
3. **`HypothesisRequest` omits `incident_id`,** yet the parser reads it from model JSON and
   the verifier fails closed to `UNKNOWN` on context mismatch.
4. `FakeLLMClient` raises a bare `IndexError` on exhaustion rather than a typed `LLMError`.

## Decision

### 1. Hexagonal split — application core, then FastAPI adapter

A new framework-independent `application` package (use-cases + the `Worker`) depends only on
the existing ports (`UnitOfWork`/repositories, `LLMClient`) plus a new `TelemetrySource`
port and the domain. FastAPI is an inbound adapter that calls the use-cases; nothing in the
application core imports FastAPI, uvicorn, psycopg, or google-genai. This keeps the core
unit-testable on the in-memory fakes with no server and no network.

### 2. `TelemetrySource` port resolves the telemetry gap (no schema change in Phase 6)

Introduce `TelemetrySource` (a `Protocol`): `async def load(tenant, incident, run) ->
tuple[SignalBaselineInput, ...]`. Phase 6 ships an in-memory fake used by tests. Wiring real
RCAEval-derived telemetry into PostgreSQL is deferred to Phase 7 (real-data integration),
which supplies a durable `TelemetrySource`. This avoids a premature schema change and keeps
the Phase 4 schema frozen while making the worker complete.

### 3. Worker loop

For each claimed job (single transaction per attempt): set investigation/job `RUNNING` →
`telemetry.load(...)` → `rank_metric_shifts` → `compile_metric_shift_ledger` → derive
`allowed_signals = frozenset(e.signal_key for e in ledger.entries)` →
`llm.propose_metric_hypotheses` → `parse_metric_hypothesis` → `verify_hypothesis` → persist
one `EvidenceRecord` per ledger entry + one `ReportRecord` (`verification_json`) → set
`SUCCEEDED`; record an `AttemptRecord` and a sanitized `AuditRecord`; `commit`.

- **Per-attempt deadline** via `asyncio.timeout`; a timeout records a `TIMEOUT` attempt.
- **Untrusted-output failure** (`LLMValidationError`) is terminal: the investigation is set
  `FAILED` with the error's stable `code` recorded as `error_code` (never model text), and the
  job `FAILED` (no retry — malformed output will not fix itself).
- **Provider failure** (`ProviderUnavailableError`/`ProviderTimeoutError`) is retryable up to
  `max_attempts` (the job returns to `QUEUED` with backoff via `available_at`); exhaustion is
  terminal `FAILED`.
- **Cancellation:** an investigation cancelled before/at claim short-circuits to `CANCELLED`.

### 4. Evidence persistence granularity

Persist **one `EvidenceRecord` per ledger entry**, keyed by the entry's content-bound
`evidence_id`, so the report's cited evidence ids resolve to stored rows. This needs a
per-entry canonical serializer, added as an **additive** `metric_evidence_entry_json` in
`domain/serialization.py` (additive, backward-compatible; the frozen ledger IDs are
unchanged). The whole verification result is persisted once via `ReportRepository.put`.

### 5. Small additive fixes to the Phase 5 boundary

- Add `incident: IncidentId` to `HypothesisRequest` so the prompt can carry it and the
  parsed hypothesis can match the ledger context (resolves gap 3).
- `FakeLLMClient` raises a typed `LLMError` (proposal exhausted) instead of `IndexError`.

Both are additive and covered by tests.

### 6. HTTP API and authentication (security)

Endpoints (async FastAPI):

- `POST /investigations` → `202 Accepted` + investigation id; honors an `Idempotency-Key`
  header mapped to the durable `idempotency_key` (idempotent creation).
- `GET /investigations/{id}` → status.
- `GET /investigations/{id}/report` → the report, or `404` (absent) / `409` (not ready).
- `GET /health` → liveness; the **only unauthenticated** route.

**Auth (per ADR 0007 — static bearer tokens + tenant scoping, not a full identity system):**
a middleware/dependency maps a bearer token to a `TenantId`; a missing/unknown token is
`401`. **Every** data query is tenant-scoped — a caller can never read another tenant's
investigation (cross-tenant access returns `404`, not `403`, to avoid existence leaks).
Tokens come from configuration/environment; no secret is logged and errors are leakage-safe
(stable problem codes, no model text or tenant data). This is a network-exposed service, so
the absence of auth on any data route would be a security defect; the design places auth on
all of them.

### 7. Dependencies (approval-gated)

Slice 6b adds `fastapi` and `uvicorn[standard]` as runtime dependencies (exact-pinned, like
psycopg/google-genai), under the same phase-aware validator (Phase 6 allowance; Phases 1–5
unchanged). `httpx` is already present (a google-genai transitive dep) and drives the ASGI
test client, so no separate test dependency is required.

### 8. Slice plan

- **6a (no new dependency):** `application` use-cases (`CreateInvestigation`,
  `GetInvestigationStatus`, `GetReport`) + `Worker` + `TelemetrySource` port + in-memory
  telemetry fake + the additive domain serializer + the Phase-5 tweaks; hermetic tests
  including an end-to-end create→enqueue→run→report on the fakes and a stalled-model test
  (N stalled fake-LLM jobs do not wedge the loop).
- **6b (adds fastapi + uvicorn):** the FastAPI app, bearer-token auth + tenant scoping,
  the routes, DI wiring, and an ASGI end-to-end test (POST→poll→report) plus a health test
  under stalled models. Governance bumps to Phase 6.

### 9. Testing strategy

The hermetic gate covers the full pipeline on in-memory persistence + `FakeLLMClient` + fake
telemetry, with no server, database, network, or credentials. The ASGI E2E runs in-process
via `httpx.ASGITransport`. Real PostgreSQL and real Gemini remain opt-in and skipped in CI.

## Consequences

### Positive

- The worker and use-cases are fully testable without a server or network; FastAPI is a thin
  edge. The `TelemetrySource` port lets Phase 7 supply real data without touching the core.
- Content-addressed evidence rows make every cited evidence id in a report resolvable.
- Auth and tenant scoping are structural properties of the control plane, not add-ons.

### Cost

- `fastapi` + `uvicorn` are the third/fourth runtime dependencies.
- The telemetry source is faked in Phase 6; a real end-to-end over PostgreSQL waits for
  Phase 7, so Phase 6's "real" run is limited to the opt-in persistence integration path.
- Two additive touches to the otherwise-frozen domain/LLM code (a serializer; a request
  field; a fake error), each behind tests.

## Rejected alternatives

- **Store raw telemetry in a Phase 6 schema table now:** a larger schema change than needed;
  deferred behind the `TelemetrySource` port until Phase 7 defines the durable shape.
- **Persist the whole ledger as one evidence row:** there is no ledger-level content id, and
  it would not let cited per-entry evidence ids resolve. Rejected.
- **Skip auth for v1 / add it later:** unacceptable for a network-exposed multi-tenant
  service; bearer-token + tenant scoping is in scope from the first endpoint.
- **Let the FastAPI layer own orchestration:** couples HTTP to the pipeline and blocks
  worker reuse. Rejected in favor of the framework-independent application core.

## Approvals (resolved 2026-07-18)

Aswani approved all three open questions:

1. **Dependencies** — `fastapi==0.139.2` and `uvicorn[standard]==0.51.0` are accepted as the
   Phase 6 runtime dependencies, pinned exactly in `pyproject.toml`/`uv.lock`; the validator's
   phase-aware allowance is extended to Phase 6 and Phases 1–5 are unchanged.
2. **Telemetry via a port now** — the `TelemetrySource` abstraction with an in-memory fake is
   accepted for Phase 6; a durable RCAEval-backed source is deferred to Phase 7.
3. **Additive touches** — the `metric_evidence_entry_json` serializer, the `incident` field on
   `HypothesisRequest`, and the typed `FakeLLMClient` exhaustion error are accepted.

## Verification (2026-07-18)

Implemented in two reviewed slices on `phase/06-control-plane` and independently reviewed.
Security fixes from review applied: the built-in OpenAPI/`/docs`/`/redoc` routes are disabled
so `/health` is the only unauthenticated route (guarded by a test), and all error bodies are
normalized to a flat, leakage-safe `{"code": ...}`.

Hermetic locked gate green: ruff, `ruff format --check`, and mypy clean; 258 unittest tests
pass with 9 skipped (the opt-in PostgreSQL integration and Gemini live-smoke tests); the
project validator passes (full) under Phase 6; `uv sync --locked` resolves. Honest scope: the
worker is exercised against the in-memory persistence fake and the deterministic LLM; an
end-to-end run over real PostgreSQL and a live Gemini call are opt-in and not part of the gate.
