# Project Context

Last verified: 2026-07-19

## Current phase

Phase 9 (ADR 0016 — runnable entrypoint + container image) is the current accepted phase on
`main`. On top of it, ADR 0017 — production telemetry ingestion via Prometheus — is in progress on
branch `feat/prometheus-telemetry`. Slices 1–3 (bounded stdlib range-query client,
series-to-signal mapper, and the `PrometheusTelemetrySource` plus the `TelemetrySource` port
change and config wiring) are implemented with the full locked hermetic gate verified green on
2026-08-22. Slice 4 (a bundled throwaway-Prometheus demo profile and the first live run) is not
started, and the ADR is still `proposed`.

## Current objective

Close the last documented v1 gap — the system had never read telemetry from a live monitoring
system — by adding a read-only Prometheus range-query source behind the existing
`TelemetrySource` port, standard-library only and with no new runtime dependency. The client is
bounded in response size, series count, and points per series; it carries a per-query deadline;
non-finite samples are dropped as gaps rather than coerced to zero (ADR 0010); and every
transport, shape, or bound failure collapses into one typed `TelemetryUnavailableError`. The
blocking `urllib` work runs off the event loop via `asyncio.to_thread`. What remains is the
demo profile and the first genuine live run: nothing in this work has opened a socket.

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

Phase 9 uses the same locked clean-checkout gate as Phases 1–8, verified green on 2026-07-18
(unittest with PostgreSQL and Gemini-live tests skipped; ruff/format/mypy clean; validator
full pass), plus a container build and smoke test:

- `uv sync --locked`
- `uv run --locked python -m compileall -q src scripts .kiro/hooks tests`
- `uv run --locked python -m unittest discover -s tests -p "test_*.py" -v`
- `uv run --locked ruff check .`
- `uv run --locked ruff format --check .`
- `uv run --locked mypy src tests`
- `uv run --locked python scripts/validate_project.py`
- `docker build -t incident-evidence-compiler:ci .` then a `/health` + `/metrics` smoke run
- `kiro-cli agent validate --path .kiro/agents/incident-orchestrator.json`
- `git diff --check`
- One independent Phase 9 implementation review

## Accepted (recent)

- Production telemetry ingestion via Prometheus is in progress (ADR 0017, devlog 0012, slices 1–3
  on `feat/prometheus-telemetry`): a bounded standard-library `query_range` client behind an
  injected `fetch`, a series-to-signal mapper that treats non-finite samples as gaps (ADR 0010)
  and fails closed on anything the domain cannot represent, and a `PrometheusTelemetrySource`
  whose blocking `urllib` work runs off the event loop via `asyncio.to_thread` and whose every
  typed failure becomes `TelemetryUnavailableError`. `TelemetrySource.load` gained a trailing
  `window: IncidentWindow`; the two pre-indexed sources accept and ignore it. No new runtime
  dependency. It has **never been run against a live Prometheus**, and the bundled demo profile
  (slice 4) is not written, so the README states both limitations explicitly. PromQL selectors are
  process-wide, so all tenants in a process see the same metrics.
- The system is runnable and containerized (ADR 0016, devlog 0010): a composition-root
  `runtime` package and `python -m incident_evidence_compiler` entrypoint wire the ports into a
  FastAPI control plane plus an in-process lifespan worker loop; configuration is environment-only
  and fail-fast (`AppConfig.from_env`), with a labelled non-model smoke LLM client
  (`FirstSignalLLMClient`) and a labelled RCAEval-backed demo telemetry source
  (`RcaevalTelemetrySource`) enabling a credential-free end-to-end boot. A multi-stage non-root
  `uv` image health-checks `/health` with the stdlib, and a shell-based CI job builds and smoke-
  tests it. No new runtime dependency; production telemetry ingestion remains an explicit non-goal.
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

Slice 4 of ADR 0017: bundle a throwaway Prometheus plus a synthetic anomaly exporter as an
optional `docker-compose` profile, run one investigation end to end against it — the first time
any of this code opens a socket — and record what breaks. Only after that does the README's
ingestion claim lose its "never pointed at a real Prometheus" caveat. Then decide whether ADR 0017
moves from `proposed` to `accepted`, and whether the process-wide selector limitation is closed in
v1 or deferred.

Also open: `runtime/prometheus.py` imports `evaluation.harness.baseline_inputs` for the scale-floor
policy (ADR 0017 item 5 sanctions it, but evaluation code in the production path is owed a refactor
slice), and the `feat/prometheus-telemetry` branch is not pushed — build-in-public pushes remain
Aswani's call, and automated shell pushes stay disabled.

### Earlier, still true

Step 4 (sealed RE2-TT held-out run) is DONE — executed once on 2026-07-19, on branch
`step/04-sealed-tt-eval`. A `--sealed-confirm "<reason>"` seam was added to
`scripts/run_evaluation.py` with three tests (commit `0a7854e`, the frozen run commit); RE2-TT
was downloaded + md5-verified + extracted outside the repo; both arms ran at `0a7854e` with the
config identical to RE2-OB (no tuning against TT). Held-out results (90 cases, 0 skipped, 0
invalid IDs): baseline Top-1 0.767 / Top-3 0.878 / MRR 0.833; verifier-gated Gemini Top-1 0.156
(0.368 answered), abstains 52/90. Aggregate label-free artifacts + protocol log + README
held-out table committed (`4f84e86`). Branch not yet pushed (build-in-public push is Aswani's
call; automated shell pushes stay disabled).

Known limitation surfaced during the run (NOT fixed, by decision): the evaluation harness loads
the whole split into memory before scoring, so RE2-TT (~6 GB RSS for 90 cases) OOMs on low free
RAM; the run needed ~8 GB free. Proper fix = a streaming score-one-discard-one path (added to
the README roadmap; deferred). See memory `re2-tt-eval-oom`.

Remaining v1 ship step: the demo recording plus build-in-public posts (Step 5). OpenTelemetry
spans and estimated cost remain deferred per the ADR 0015 cut order.
