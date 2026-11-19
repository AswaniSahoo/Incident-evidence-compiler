# ADR 0002: V1 Product Scope

- Status: Accepted
- Status note, 2026-11-19: what the code at `e02d918` does today; the record below is unchanged history. Paths are under `src/incident_evidence_compiler/`.
  - Only the metric ledger is compiled at run time (`application/worker.py:197`). The change-event ledger is implemented, but `compile_change_event_ledger` has no caller outside tests, and logs and traces are not ingested.
  - The persisted report carries verdicts, per-predicate reasons and cited evidence IDs (`domain/serialization.py:317-325, 425-434`), with the `baseline_ranking` beside it; it has no provenance block and no diagnostic-check section.
  - There is no cost metric (`application/worker.py:119-133`), and the abstention policy is an uncalibrated default (`application/worker.py:61-66`).
- Date: 2026-07-16

## Problem

Incident evidence is fragmented, incomplete, time-sensitive, and untrusted. A model can propose explanations but must not be the authority that decides whether evidence exists or whether a causal statement is supported.

## Decision

V1 accepts an authorized incident identifier, compiles bounded metrics/logs/traces/change events into a temporal evidence ledger, asks Gemini for a restricted hypothesis document, verifies allow-listed predicates deterministically, and persists a replayable report.

Verification has three outcomes:

- `SUPPORTED`
- `REFUTED`
- `UNKNOWN`

The report contains supporting evidence, contradicting evidence, unknowns, provenance, and non-destructive diagnostic checks.

## V1 non-goals

- Arbitrary SQL, shell, PromQL, URL, or Kubernetes command generation
- Autonomous remediation
- Generic chat or web search
- Multi-agent runtime roles
- LangGraph or MCP orchestration
- Fine-tuning or multiple model providers
- Redis as durable state
- Kubernetes or multi-cloud deployment
- A polished frontend

## Success evidence

Success requires held-out RCA quality, evidence integrity, calibrated abstention, tenant isolation, durable worker recovery, replay completeness, latency/cost reporting, and fault-test results. Framework count is not a success metric.
