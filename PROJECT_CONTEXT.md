# Project Context

Last verified: 2026-07-16

## Current phase

Phase 0 complete — independent repository foundation accepted.

## Current objective

Preserve the validated foundation and wait for Aswani before beginning the Phase 1 domain baseline.

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

Phase 0 contains governance, documentation, and standard-library tests only. Product scope/provenance commit: `e1391acda89e8294203ed5fec2fce5e42b86a2c8`. Kiro governance/validation commit: `c6fbf567344c12fc95ad359e695eb90633019f61`. No application package, runtime dependencies, benchmark data, cloud resources, remote, public license, or push has been added.

## Validation

The following passed against committed `HEAD` `c6fbf567344c12fc95ad359e695eb90633019f61`:

- `git show --check --oneline --format=fuller HEAD`
- `python -m py_compile scripts/validate_project.py .kiro/hooks/project_hook.py tests/test_project_hook.py tests/test_validate_project.py`
- `python -m unittest discover -s tests -p "test_*.py" -v` — 16 tests
- `python scripts/validate_project.py`
- `python scripts/validate_project.py --quick`
- `kiro-cli agent validate --path .kiro/agents/incident-orchestrator.json`

Independent pre-commit review returned `PRECOMMIT_APPROVED`. Hosted CI was not run because this repository intentionally has no remote; Aswani will push manually.

## Open decisions

- Public license for this independently written repository.
- Exact Phase 1 package/dependency versions after the first code contract is approved.
- Final RCAEval data split and leakage policy after inspecting the pinned release.

## Next action

After Aswani confirms Phase 1, create `phase/01-domain-baseline` and implement only domain contracts, a pinned dataset manifest, leakage checks, and a deterministic telemetry-only baseline. Do not push; Aswani will push manually.
