# Incident Evidence Compiler

A clean-room, production-oriented learning project for evidence-grounded incident investigation.

## Status

**Phase 0 — foundation and decision records.** No production implementation exists yet.

The system will ingest bounded microservice incident telemetry, build a temporal evidence ledger, allow Gemini to propose restricted diagnostic hypotheses, and verify those hypotheses with deterministic predicates before producing a report.

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
python scripts/validate_project.py
```

## Project governance

- [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) — compact current state loaded by the project agent.
- [`AGENTS.md`](AGENTS.md) — agent and contributor operating contract.
- [`.kiro/steering/`](.kiro/steering/) — persistent Kiro workspace rules.
- [`docs/decisions/`](docs/decisions/) — architecture decision records.
- [`docs/devlog/`](docs/devlog/) — evidence-based phase journals and blog source material.

See [`docs/architecture/overview.md`](docs/architecture/overview.md) for the intended boundaries.
