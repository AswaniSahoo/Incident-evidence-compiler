# Project Context

Last verified: 2026-08-30

## Current phase

Phase 9 (ADR 0016) and ADR 0017 (production Prometheus ingestion) are **accepted and merged to
`main`** (`bd1bb64`, PR #4). On top of that, ADR 0018 (payment-infrastructure incident demo) and ADR 0019 (expose the baseline
ranking as an additive nullable `baseline_ranking` field) are **accepted and merged to `main`**
(PR #5 plus direct commits). ADR 0018 reskins the ADR 0017 profile into a bank-router deploy
incident (`bank_router` faulty, `ledger_db` a deliberate healthy decoy) with no domain, port, or
verifier change; ADR 0019 persists the ranking additively (migration `0002`, verification schema
untouched). The full locked gate is green (342 tests), and the Postgres `SKIP LOCKED` durability
suite was verified against `postgres:16` (devlog 0014).
A live **Vertex** run (2026-08-23, `gemini-2.5-flash`, project `iec-live-demo`, isolated from the
ambient `climate-risk-agent` project) had Gemini propose four predicates; the verifier returned
`supported` only for `bank_router_latency_increase` (cited evidence `sha256:758e…`) and `unknown`
for the other three, including the `ledger_db` decoy, one verified-true, three guesses withheld,
zero false assertions. (ADR 0017's earlier `checkout` runs and the divergent-default Gemini fix are
recorded in devlog 0012.)

## Current objective

Present IEC as a payment-infrastructure incident investigator for an evaluated, payments-shaped
setting (the immediate driver is the Razorpay AI Buildathon, Open Track; applications close
2026-09-05), without moving the frozen domain or faking a vendor integration. The reskin is
confined to demo artifacts (exporter signal names, `IEC_PROM_QUERIES`, driver label, README, ADR
0018, devlog 0013); the data stays synthetic and labelled. The durability evidence (devlog 0014)
and the baseline-ranking API (ADR 0019, devlog 0015) are both done on `main`.

Hardening pass, 2026-08-30, after an external senior-engineer review. Boundary fuzzing added
(devlog 0016): 3,000 generated hostile inputs assert that only typed `LLMValidationError` and
`PrometheusError` ever escape the untrusted LLM and telemetry boundaries. The harness initially
passed while covering the allow-list branch zero times out of 1,500 cases, which the outcome
distribution exposed; a hallucinated-signal strategy took that branch to 133 hits. Em-dashes were
removed repo-wide (263 across 49 files) and two stale README claims corrected. Devlog 0017 records
the divergent default-model incident so the Buildathon "what broke" answer links to a published
artifact. The README now leads with the verifier refusing a plausible answer, as a table rather than
a Mermaid block, so nothing above the fold depends on GitHub's diagram renderer.

**The only remaining Buildathon item is the 5-minute pitch video.** The script, screen direction,
form answer and production plan are written in the gitignored `docs/learning/`. Note: `mermaid-cli`
cannot pre-render diagrams on this machine (puppeteer fails to launch Chromium), so the two Mermaid
blocks stay inline and unrendered; they sit below the fold and are not load-bearing.

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

- Production telemetry ingestion via Prometheus is implemented (ADR 0017, devlog 0012, slices 1–4
  on `feat/prometheus-telemetry`): a bounded standard-library `query_range` client behind an
  injected `fetch`, a series-to-signal mapper that treats non-finite samples as gaps (ADR 0010)
  and fails closed on anything the domain cannot represent, and a `PrometheusTelemetrySource`
  whose blocking `urllib` work runs off the event loop via `asyncio.to_thread` and whose every
  typed failure becomes `TelemetryUnavailableError`. `TelemetrySource.load` gained a trailing
  `window: IncidentWindow`; the two pre-indexed sources accept and ignore it. No new runtime
  dependency. **Verified live on 2026-08-22** against a real Prometheus (`v3.6.0`) scraping a
  synthetic exporter via the bundled `demo` compose profile: 8 signals / 35 points ingested, the
  baseline ranked the injected `checkout` fault first and second (20.19 and 18.24 vs ≤ 0.29 for
  healthy signals), and the report came back `unknown`/`weak_evidence` because the non-model smoke
  client names the lexicographically-first signal, which is flat, the verifier correctly refused
  it. With Prometheus stopped, the investigation terminated as `failed` with no retry storm and no
  transport detail in the logs. The data is synthetic, so this proves the ingestion path, not
  diagnostic accuracy. PromQL selectors are process-wide, so all tenants in a process see the same
  metrics.
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

The immediate goal is the **Razorpay AI Buildathon** (Open Track, applications close 2026-09-05):
the repo, ADRs, sealed held-out metrics, and the live Vertex run already satisfy the "public repo +
architecture docs + honest metrics + working, not prototype" bar; the one net-new artifact is a
**5-minute pitch video**. Positioning notes: `docs/learning/razorpay-buildathon.md` (private).

Two items this file previously listed as pending are done: `feat/prometheus-telemetry` merged to
`main` at `bd1bb64` (PR #4), and ADR 0019 shipped the `baseline_ranking` field (migration `0002`,
serializer `baseline-ranking.v1`, `api/app.py`).

Deferred (README roadmap / backlog, not blockers): surfacing `baseline_ranking` where a reader can
see it, the field ships over HTTP but `scripts/demo_live_investigation.py` never prints it and the
README API section never documents it; process-wide vs per-tenant PromQL selectors; and a refactor
so the production path stops importing `evaluation.harness.baseline_inputs` for the scale-floor
policy (ADR 0017 item 5 sanctions the current import).

### Earlier, still true

Step 4 (sealed RE2-TT held-out run) is DONE, executed once on 2026-07-19, on branch
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
