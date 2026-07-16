# Project Context

Last verified: 2026-07-16

## Current phase

Phase 0 — independent-review fixes validated; final re-review and root commit pending.

## Current objective

Close the foundation phase with independent approval, a reviewed foundation commit, and a small evidence update before application code is written.

## Product

Incident Evidence Compiler: a multi-tenant asynchronous service that compiles microservice telemetry into a temporal evidence ledger, accepts restricted hypotheses from Gemini, verifies them deterministically as `SUPPORTED`, `REFUTED`, or `UNKNOWN`, and returns a replayable incident report.

## Accepted decisions

- Independent rewrite; no upstream source code is copied.
- RCAEval RE2 is the planned benchmark, subject to a pinned dataset/license manifest in Phase 1.
- PostgreSQL will be the durable source of truth and initial job queue.
- Redis is initially limited to disposable cross-process admission control.
- Model-generated SQL, shell commands, remediation, generic chat, LangGraph, MCP, and multi-agent runtime behavior are out of v1 scope.
- Gemini is accessed through one asynchronous provider interface; tests use a deterministic fake.
- Every accepted material conclusion must resolve to same-tenant, same-run evidence and a passing verifier trace.

## Provenance

Reference prototype: https://github.com/yashprogrammer/EnterpriseRAG_live.git at commit `96cbbd3a7e4f012240c48c1fead9c838e9bb1b6b`. The upstream repository has no license file as verified on 2026-07-16. It remains a read-only audit reference.

## Current repository state

Governance, documentation, and standard-library hook tests only. No application package, runtime dependencies, benchmark data, cloud resources, remote, or public license have been added.

## Validation

The Phase 0 local gate is:

- `python -m py_compile scripts/validate_project.py .kiro/hooks/project_hook.py tests/test_project_hook.py tests/test_validate_project.py`
- `python -m unittest discover -s tests -p "test_*.py" -v`
- `python scripts/validate_project.py`
- `python scripts/validate_project.py --quick`
- `kiro-cli agent validate --path .kiro/agents/incident-orchestrator.json`

All passed after the first independent review findings were fixed. Root-commit whitespace evidence remains pending until the commit exists.

## Open decisions

- Public license for this independently written repository.
- Exact Phase 1 package/dependency versions after the first code contract is approved.
- Final RCAEval data split and leakage policy after inspecting the pinned release.

## Next action

Obtain final independent review approval, commit the Phase 0 foundation, point local `main` at the accepted root commit, and stop before Phase 1 design or implementation.
