# Project Context

Last verified: 2026-07-16

## Current phase

Phase 1 — domain contracts and deterministic baseline — complete. Phase 2 decision subphase is next.

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

The local Phase 1 implementation includes dependency-free domain contracts, the exact robust metric-shift baseline, the pinned RCAEval manifest, bounded local adapter, evaluation-only sidecar, random UUIDv4 case IDs, synthetic fixtures, locked tooling, and phase-aware CI. No raw benchmark data has been downloaded. No remote is configured.

## Validation

Phase 1 must pass this locked clean-checkout gate:

- `uv sync --locked`
- `uv run --locked python -m compileall -q src scripts .kiro/hooks tests`
- `uv run --locked python -m unittest discover -s tests -p "test_*.py" -v`
- `uv run --locked ruff check .`
- `uv run --locked ruff format --check .`
- `uv run --locked mypy src tests`
- `uv run --locked python scripts/validate_project.py`
- `kiro-cli agent validate --path .kiro/agents/incident-orchestrator.json`
- `git diff --check`
- Independent review recorded in the Phase 1 devlog

## Open decisions

- Public license for this independently written repository.
- Whether and when Aswani wants to download the 1.19 GB RE2-OB archive for real-data integration.
- Whether RE2-SS becomes a secondary development set after the OB baseline is measured.

## Next action

Begin the Phase 2 decision subphase from the accepted product flow: choose the smallest coherent boundary between temporal evidence-ledger contracts and deterministic tri-state predicate verification, freeze acceptance criteria, and create a local Phase 2 branch. Do not download RCAEval data, configure a remote, or push.
