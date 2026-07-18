# Project Context

Last verified: 2026-07-18

## Current phase

Phase 8 — observability (Prometheus metrics) — is implemented on branch `phase/07-real-data` with the full locked hermetic gate verified green (2026-07-18); it is pending one independent review and Aswani's explicit commit approval. Phases 0–7 are committed in this branch's history (through the Phase 7 real-data evaluation); Phase 8 adds dependency-free metrics and an open `/metrics` endpoint as part of v1 hardening.

## Current objective

Make the pipeline observable for v1 hardening (Phase 8): a dependency-free `observability`
package exposing a thread-safe `MetricsRegistry` of counters and histograms in the Prometheus
text exposition format (cumulative buckets with `_sum`/`_count`/`+Inf`); worker
instrumentation of per-stage latency, job outcomes, provider-timeout rate, LLM token counts,
and verdict distribution recorded into an injected registry with no tenant/PII labels; and an
open `GET /metrics` route on the control plane. No new runtime dependency
(`pyproject.toml`/`uv.lock` unchanged); the label-safety and hermetic-CI invariants are
unchanged (ADR 0015, devlog 0009).

## Product

Incident Evidence Compiler: a multi-tenant asynchronous service that compiles microservice telemetry into a temporal evidence ledger, accepts restricted hypotheses from Gemini, verifies them deterministically as `SUPPORTED`, `REFUTED`, or `UNKNOWN`, and returns a replayable incident report.

## Accepted decisions

- Independent rewrite; no upstream source code is copied.
- The repository's own code, docs, and config are licensed under Apache-2.0 (ADR 0008); RCAEval data is separately licensed and never committed.
- RCAEval release `1.2.0` is pinned at commit `bc49dbd85bd14032101fb9a69a5a37e9d6d55178`.
- RE2-OB is development/calibration, RE2-TT is sealed by default, and RE2-SS is reserved.
- Raw RCAEval data is not committed or redistributed; the pinned upstream RCAEval repository states MIT for the authors' code/datasets while Zenodo archive metadata states `cc-by-4.0`, and both notices are documented.
- Runtime code remains Python 3.12 standard-library-only; Ruff `0.15.13`, mypy `2.1.0`, and uv `0.11.17` remain exactly pinned development/build tools.
- The Phase 1 baseline emits ranked suspicion or abstention, never a causal claim.
- Phase 2 binds every metric evaluation to immutable provenance, uses content-bound evidence IDs, and verifies only flat descriptive increase/decrease predicates.
- The verifier uses the frozen baseline minimum score inclusively; global ranking margin remains diagnostic and does not establish or suppress a signal-specific descriptive observation.
- Context mismatch and causal semantics fail closed as `UNKNOWN`; invalid contracts raise stable leakage-safe domain errors.
- Phase 3 adds bounded change/deployment events as a separate `change-event-ledger.v1` with content-bound IDs under a distinct domain separator, leaving the frozen metric ledger and its IDs unchanged.
- Change events are verified as descriptive temporal co-occurrence only, independently of metric shifts; no cross-signal correlation and no causal inference.
- Change co-occurrence semantics are three-valued: in-phase presence is `SUPPORTED`, presence recorded only outside the asserted phase is `REFUTED` (the ledger is the authoritative record of observed changes), and total absence is `UNKNOWN`.
- PostgreSQL will be the durable source of truth and initial job queue in a later phase.
- Redis is initially limited to disposable cross-process admission control in a later phase.
- Model-generated SQL, shell commands, remediation, generic chat, LangGraph, MCP, and multi-agent runtime behavior are out of v1 scope.
- Gemini is accessed through one asynchronous provider interface in a later phase; tests use a deterministic fake.
- Every accepted material conclusion must resolve to same-tenant, same-run evidence and a passing verifier trace.

## Provenance

Reference prototype: https://github.com/yashprogrammer/EnterpriseRAG_live.git at commit `96cbbd3a7e4f012240c48c1fead9c838e9bb1b6b`. It remains a read-only audit reference. RCAEval dataset provenance is recorded in `docs/datasets/rcaeval-re2.md`.

## Current repository state

Phase 1 is accepted at local commit `8d0ba39`. Phase 2 is accepted at commit `29b3212`. The Phase 3 boundary is `a17aa7b`. Since then, `main` advanced through the evidence-module refactor (`fc5f057`), ADR 0009 (`21bd72e`), and ADR 0010 (`773d39d`), and is published to and tracking the GitHub remote `origin` (`AswaniSahoo/Incident-evidence-compiler`) at `773d39d`. Local AI-assistant working notes (`CLAUDE.md`) are excluded via `.gitignore` and were removed from local history prior to the first push; no such traces exist in the published repository. RE2-OB has been downloaded and checksum-verified but is stored and extracted outside the repository root and is never committed; only synthetic fixtures are committed. RE2-TT stays sealed; RE2-SS reserved.

## Validation

Phase 8 uses the same locked clean-checkout gate as Phases 1–7, verified green on 2026-07-18
(unittest with PostgreSQL and Gemini-live tests skipped; ruff/format/mypy clean; validator
full pass):

- `uv sync --locked`
- `uv run --locked python -m compileall -q src scripts .kiro/hooks tests`
- `uv run --locked python -m unittest discover -s tests -p "test_*.py" -v`
- `uv run --locked ruff check .`
- `uv run --locked ruff format --check .`
- `uv run --locked mypy src tests`
- `uv run --locked python scripts/validate_project.py`
- `kiro-cli agent validate --path .kiro/agents/incident-orchestrator.json`
- `git diff --check`
- One independent Phase 8 implementation review

## Accepted (recent)

- Observability is Prometheus-only and dependency-free (ADR 0015, devlog 0009): a
  standard-library `observability` package renders the Prometheus text exposition format; the
  `Worker` records `iec_worker_jobs_total{outcome}`, `iec_worker_stage_duration_seconds{stage}`,
  `iec_provider_timeouts_total`, `iec_llm_tokens_total{kind}`, and
  `iec_investigation_verdicts_total{verdict}` into an injected registry with no tenant/PII
  labels; the control plane exposes an open `GET /metrics`. OpenTelemetry spans and estimated
  cost are deferred per the cut order. No new runtime dependency; the phase-aware validator
  covers Phase 8. AI-assistant local traces now also gitignore the whole `.claude/` and
  `.serena/` tool directories so they are never published.
- RE2-OB is acquired locally under a guardrail (ADR 0009): downloaded and checksum-verified, stored and extracted outside the repository root so the validator's no-raw-data guarantee stays intact, never committed; CI stays hermetic on synthetic fixtures and fakes; RE2-TT stays sealed and RE2-SS reserved.
- Missing and non-finite metric cells are gaps, not failures (ADR 0010): the loader drops the point for that signal at that timestamp (never zero), keeps the `time` column strict, treats a non-empty non-numeric cell as a hard `INVALID_NUMBER`, and exposes `dropped_cell_count` on `ParsedCase`. Verified against RE2-OB: parse coverage rose from 19/90 to 88/90 cases.

## Open decisions

- Whether to tolerate a trailing row with an empty `time` cell: 2 of 90 RE2-OB cases (`checkoutservice_cpu/2`, `checkoutservice_mem/2`) still fail `invalid_timestamp` on a truncated final row. Distinct from missing metric cells; deferred.
- Derive a small sanitized, label-free committed fixture from real RE2-OB shapes (deferred to its own reviewable slice; ADR 0009 commits no derived data).
- Whether RE2-SS becomes a secondary development set after the OB baseline is measured.

## Next action

Phase 8 (observability) is code-complete with the full locked hermetic gate green
(ruff/format/mypy clean; unittest 286 tests OK with PostgreSQL and Gemini-live tests skipped;
validator full pass). It awaits one independent review and Aswani's explicit commit approval;
`pyproject.toml`/`uv.lock` are unchanged and the metric set carries no tenant/PII labels.

Remaining v1 ship steps after the Phase 8 commit: a runnable server entrypoint wiring a shared
registry into both the control plane and the worker under `uvicorn`, plus a Dockerfile and a
docker-build CI gate (Step 3); one authorized sealed RE2-TT run (Step 4, opt-in and
unauthorized by default); and the demo recording plus build-in-public posts (Step 5).
OpenTelemetry spans and estimated cost remain deferred per the ADR 0015 cut order.
