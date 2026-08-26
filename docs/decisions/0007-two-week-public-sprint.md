# ADR 0007: Two-week public sprint to v1 with recorded scope cuts

- Date: 2026-07-17
- Status: Accepted

## Context

Aswani has a time-boxed external commitment in roughly two weeks that bounds available hours. The portfolio thesis positions this repository as the production-AI-systems flagship complementing `climate-risk-agent`. Available budget: ~4 hours/day for 14 days (~56 hours), with other protected commitments running in parallel. The original product design assumed roughly four full-time weeks.

## Decision

1. Execute the sprint per `MASTER-PLAN.md`: publish the repository publicly on Day 1 (build-in-public), then deliver persistence, the async provider boundary, the control plane + worker, real RCAEval RE2-OB evaluation, one sealed RE2-TT run, and OTel/Prometheus observability, behind the existing phase-gate validation, unchanged.
2. Select a public license on Day 1 and record it (separate ADR); publication is blocked until then per README.
3. Scope cuts for v1, all moved to a v2 backlog rather than silently dropped: runbook RAG corpus and retrieval; Redis admission control; Grafana dashboard (Prometheus endpoint only); OIDC/RBAC depth (static bearer tokens + tenant-scoped queries remain); calibrated abstention with risk–coverage curve (existing typed abstention remains; no uncalibrated curve is published); SSE streaming; DELETE endpoint; astronomy-shop demo; RE2-SS.
4. Slippage degrades scope via the MASTER-PLAN cut order; it never waives tests, leakage sanitation, sealed-test-set protocol, or documentation truthfulness.

## Consequences

- v1 demonstrates the project's actual novelty (evidence ledger + restricted hypotheses + deterministic tri-state verification, operated as an async multi-tenant service) within the available time.
- The repository's history becomes public early, including in-progress states; the phase-gate rule keeps every pushed commit verified.
- Some design elements the devlogs anticipated (retrieval, Redis, calibration) are explicitly deferred, and README/PROJECT_CONTEXT must describe v1 without implying they exist.
