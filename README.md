# Incident Evidence Compiler

A clean-room, production-oriented learning project for evidence-grounded incident investigation.

## Status

**Phase 1 — domain contracts, deterministic baseline, and bounded RCAEval adapter.**

The repository now contains a standard-library-only Python domain, a replayable robust
metric-shift baseline with typed abstention, and a label-safe adapter for locally extracted
RCAEval RE2 data. Only synthetic benchmark fixtures are committed.

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

No public license has been selected for this new repository yet. Do not publish it until that decision is recorded.

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
