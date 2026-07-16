# Project Context

Last verified: 2026-07-16

## Current phase

Phase 2 — immutable metric evidence and deterministic verification — complete.

## Current objective

Compile Phase 1 metric evaluations into a tenant/incident/run-bound immutable evidence ledger, verify a restricted descriptive hypothesis with exact `SUPPORTED`, `REFUTED`, or `UNKNOWN` semantics, and serialize both artifacts canonically without adding infrastructure or model dependencies.

## Product

Incident Evidence Compiler: a multi-tenant asynchronous service that compiles microservice telemetry into a temporal evidence ledger, accepts restricted hypotheses from Gemini, verifies them deterministically as `SUPPORTED`, `REFUTED`, or `UNKNOWN`, and returns a replayable incident report.

## Accepted decisions

- Independent rewrite; no upstream source code is copied.
- RCAEval release `1.2.0` is pinned at commit `bc49dbd85bd14032101fb9a69a5a37e9d6d55178`.
- RE2-OB is development/calibration, RE2-TT is sealed by default, and RE2-SS is reserved.
- Raw RCAEval data is not committed or redistributed; the pinned upstream RCAEval repository states MIT for the authors' code/datasets while Zenodo archive metadata states `cc-by-4.0`, and both notices are documented.
- Runtime code remains Python 3.12 standard-library-only; Ruff `0.15.13`, mypy `2.1.0`, and uv `0.11.17` remain exactly pinned development/build tools.
- The Phase 1 baseline emits ranked suspicion or abstention, never a causal claim.
- Phase 2 binds every metric evaluation to immutable provenance, uses content-bound evidence IDs, and verifies only flat descriptive increase/decrease predicates.
- The verifier uses the frozen baseline minimum score inclusively; global ranking margin remains diagnostic and does not establish or suppress a signal-specific descriptive observation.
- Context mismatch and causal semantics fail closed as `UNKNOWN`; invalid contracts raise stable leakage-safe domain errors.
- PostgreSQL will be the durable source of truth and initial job queue in a later phase.
- Redis is initially limited to disposable cross-process admission control in a later phase.
- Model-generated SQL, shell commands, remediation, generic chat, LangGraph, MCP, and multi-agent runtime behavior are out of v1 scope.
- Gemini is accessed through one asynchronous provider interface in a later phase; tests use a deterministic fake.
- Every accepted material conclusion must resolve to same-tenant, same-run evidence and a passing verifier trace.

## Provenance

Reference prototype: https://github.com/yashprogrammer/EnterpriseRAG_live.git at commit `96cbbd3a7e4f012240c48c1fead9c838e9bb1b6b`. It remains a read-only audit reference. RCAEval dataset provenance is recorded in `docs/datasets/rcaeval-re2.md`.

## Current repository state

Phase 1 is accepted at local commit `8d0ba39`. Phase 2 decision, ledger, and verifier commits are `c167a54`, `b49866a`, and `19e3c90` on `phase/02-evidence-contracts`; final evidence commit is pending. No raw benchmark data has been downloaded and no remote is configured.

## Validation

Phase 2 uses the same locked clean-checkout gate as Phase 1:

- `uv sync --locked`
- `uv run --locked python -m compileall -q src scripts .kiro/hooks tests`
- `uv run --locked python -m unittest discover -s tests -p "test_*.py" -v`
- `uv run --locked ruff check .`
- `uv run --locked ruff format --check .`
- `uv run --locked mypy src tests`
- `uv run --locked python scripts/validate_project.py`
- `kiro-cli agent validate --path .kiro/agents/incident-orchestrator.json`
- `git diff --check`
- One independent Phase 2 implementation review

## Open decisions

- Public license for this independently written repository.
- Whether and when Aswani wants to download the 1.19 GB RE2-OB archive for real-data integration.
- Whether RE2-SS becomes a secondary development set after the OB baseline is measured.
- Which bounded telemetry type extends the metric-only evidence ledger after Phase 2.

## Next action

Finalize the Phase 2 evidence commit, verify exact HEAD, fast-forward local `main`, and open a clean Phase 3 decision branch. Choose the next bounded vertical slice before implementation; do not assume whether it is another telemetry type, persistence, or the model-provider boundary. Do not download datasets, configure a remote, or push.
