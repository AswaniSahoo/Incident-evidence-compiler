# Project Context

Last verified: 2026-07-16

## Current phase

Phase 1 — domain contracts and deterministic baseline.

## Current objective

Implement a framework-independent incident domain, a deterministic metric-shift baseline with explicit abstention, and a bounded label-safe RCAEval RE2 adapter using synthetic fixtures.

## Product

Incident Evidence Compiler: a multi-tenant asynchronous service that compiles microservice telemetry into a temporal evidence ledger, accepts restricted hypotheses from Gemini, verifies them deterministically as `SUPPORTED`, `REFUTED`, or `UNKNOWN`, and returns a replayable incident report.

## Accepted decisions

- Independent rewrite; no upstream source code is copied.
- RCAEval release `1.2.0` is pinned at commit `bc49dbd85bd14032101fb9a69a5a37e9d6d55178`.
- RE2-OB is development/calibration, RE2-TT is sealed by default, and RE2-SS is reserved.
- Raw RCAEval data is not committed or redistributed; the pinned upstream RCAEval repository states MIT for the authors' code/datasets while Zenodo archive metadata states `cc-by-4.0`, and both notices are documented.
- Phase 1 runtime code uses only the Python 3.12 standard library; Ruff `0.15.13` and mypy `2.1.0` are pinned development tools.
- The baseline emits ranked suspicion or abstention, never a causal or tri-state verification claim.
- PostgreSQL will be the durable source of truth and initial job queue in a later phase.
- Redis is initially limited to disposable cross-process admission control in a later phase.
- Model-generated SQL, shell commands, remediation, generic chat, LangGraph, MCP, and multi-agent runtime behavior are out of v1 scope.
- Gemini is accessed through one asynchronous provider interface in a later phase; tests use a deterministic fake.
- Every accepted material conclusion must resolve to same-tenant, same-run evidence and a passing verifier trace.

## Provenance

Reference prototype: https://github.com/yashprogrammer/EnterpriseRAG_live.git at commit `96cbbd3a7e4f012240c48c1fead9c838e9bb1b6b`. It remains a read-only audit reference. RCAEval dataset provenance is recorded in `docs/datasets/rcaeval-re2.md`.

## Current repository state

Local branch `phase/01-domain-baseline` starts from accepted Phase 0 commit `02584ce`. No remote is configured and no push will occur until Aswani decides after Phase 3 or later. No application code or raw benchmark data has been added yet.

## Validation

Phase 1 must first make project governance phase-aware, then pass this clean-checkout gate:

- `uv sync --locked`
- `uv run python -m unittest discover -s tests -p "test_*.py" -v`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src tests`
- `uv run python scripts/validate_project.py`
- `kiro-cli agent validate --path .kiro/agents/incident-orchestrator.json`
- Independent review recorded in the Phase 1 devlog

## Open decisions

- Public license for this independently written repository.
- Whether and when Aswani wants to download the 1.19 GB RE2-OB archive for real-data integration.
- Whether RE2-SS becomes a secondary development set after the OB baseline is measured.

## Next action

Commit the Phase 1 decision pack, then implement pure domain value objects and the deterministic baseline with synthetic tests. Do not download RCAEval data and do not push.
