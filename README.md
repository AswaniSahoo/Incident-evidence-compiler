# Incident Evidence Compiler

A clean-room, production-oriented learning project for evidence-grounded incident investigation.

## Status

**Phase 3 — bounded change-event co-occurrence evidence (complete).**

The repository contains a standard-library-only Python domain: a replayable robust metric-shift
baseline with typed abstention, an immutable content-addressed metric evidence ledger, a
deterministic metric-shift verifier, a separate bounded change-event ledger with a tri-state
temporal co-occurrence verifier, canonical leakage-safe serialization, and a label-safe adapter
for locally extracted RCAEval RE2 data. There is no infrastructure, API, or model dependency yet.
Only synthetic benchmark fixtures are committed; raw RCAEval data is never committed.

The active plan is a two-week public sprint to an evaluated v1 — see [`MASTER-PLAN.md`](MASTER-PLAN.md).

## Why this project exists

Operational incidents produce fragmented and sometimes contradictory metrics, logs, traces, and deployment events. Language models can summarize this evidence, but they must not be trusted to invent data access, execute arbitrary queries, or assert unsupported causes.

This project asks:

> How can an AI system propose useful incident hypotheses while every accepted conclusion remains tenant-authorized, temporally valid, replayable, and linked to verifiable evidence?

## Engineering principles

- Contracts before orchestration.
- Deterministic baseline before an LLM.
- Unknown is distinct from false.
- PostgreSQL is the durable source of truth.
- Model output is untrusted input.
- External calls are bounded by deadlines and budgets.
- Features must earn their complexity through tests or measurements.
- Documentation must not claim more than committed evidence proves.

## Provenance

This is an independent rewrite. It contains no source copied from `yashprogrammer/EnterpriseRAG_live`. That public repository was audited as a learning prototype and is cited in [`docs/provenance.md`](docs/provenance.md).

## License

This project's source, documentation, and configuration are licensed under the Apache License 2.0
— see [`LICENSE`](LICENSE) and [`docs/decisions/0008-apache-2.0-license.md`](docs/decisions/0008-apache-2.0-license.md).
RCAEval dataset licensing is separate and documented in
[`docs/datasets/rcaeval-re2.md`](docs/datasets/rcaeval-re2.md); raw benchmark data is never committed.

## Current validation

```bash
uv sync --locked
uv run --locked python -m unittest discover -s tests -p "test_*.py" -v
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src tests
uv run --locked python scripts/validate_project.py
kiro-cli agent validate --path .kiro/agents/incident-orchestrator.json
```

## Project governance

- [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) — compact current state loaded by the project agent.
- [`AGENTS.md`](AGENTS.md) — agent and contributor operating contract.
- [`.kiro/steering/`](.kiro/steering/) — persistent Kiro workspace rules.
- [`docs/decisions/`](docs/decisions/) — architecture decision records.
- [`docs/devlog/`](docs/devlog/) — evidence-based phase journals and blog source material.

See [`docs/architecture/overview.md`](docs/architecture/overview.md) for the intended boundaries.
