# Project Context

Last verified: 2026-07-17

## Current phase

Phase 3 — bounded change-event co-occurrence evidence — complete.

## Current objective

Extend the immutable evidence ledger with bounded change/deployment events, bind them to the same tenant/incident/run context, and verify a restricted temporal co-occurrence hypothesis deterministically as `SUPPORTED`, `REFUTED`, or `UNKNOWN` — as descriptive timing only, never a causal claim — while serializing both artifacts canonically without adding infrastructure or model dependencies.

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

Phase 1 is accepted at local commit `8d0ba39`. Phase 2 is accepted at commit `29b3212`. Phase 3 change-event decision, ledger/contracts, verifier, serialization, validation-evidence, sprint-plan, and license commits landed on `main` at commit `a17aa7b`, published to the GitHub remote `origin` (`AswaniSahoo/Incident-evidence-compiler`), with `main` tracking `origin/main`. Local AI-assistant working notes (`CLAUDE.md`) are excluded from version control via `.gitignore` and were removed from local history prior to the first push; no such traces exist in the published repository. No raw benchmark data has been downloaded; only synthetic fixtures are committed.

## Validation

Phase 3 uses the same locked clean-checkout gate as Phases 1 and 2:

- `uv sync --locked`
- `uv run --locked python -m compileall -q src scripts .kiro/hooks tests`
- `uv run --locked python -m unittest discover -s tests -p "test_*.py" -v`
- `uv run --locked ruff check .`
- `uv run --locked ruff format --check .`
- `uv run --locked mypy src tests`
- `uv run --locked python scripts/validate_project.py`
- `kiro-cli agent validate --path .kiro/agents/incident-orchestrator.json`
- `git diff --check`
- One independent Phase 3 implementation review

## Open decisions

- Confirm and record the guardrailed real-data ADR (0009): download RE2-OB now, derive a small sanitized label-free committed fixture, ground development in real shapes, keep CI hermetic on fixtures/fakes, and keep RE2-TT sealed.
- Whether RE2-SS becomes a secondary development set after the OB baseline is measured.
- Order of post-publish slices: the `evidence.py` refactor first, then the durable persistence boundary (Phase 4), per MASTER-PLAN.

## Next action

Phase 3 is published under Apache-2.0 at `origin/main`, and the metric evidence module is now split into a focused `evidence/` package (behavior-preserving; full gate green, public API unchanged). Next: (1) confirm and record the guardrailed real-data ADR (0009) and download RE2-OB; (2) begin Phase 4 — the durable persistence boundary — against in-memory fakes per MASTER-PLAN, keeping CI hermetic.
