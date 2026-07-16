# ADR 0002: V1 Product Scope

- Status: Accepted
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
