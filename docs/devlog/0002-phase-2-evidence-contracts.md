# Phase 2: Evidence Before Explanations

- Date: 2026-07-16
- Status: In progress

## Problem

A deterministic score is not yet an auditable investigation artifact. It needs explicit run context, stable evidence identity, a restricted claim language, and a verifier that distinguishes contradiction from missing evidence.

## First principle

Preserve observed evidence and its provenance before asking any model to interpret it. A descriptive metric shift can be verified locally; a causal statement cannot be recovered from a ranking and must remain unknown.

## Decision

Build the smallest complete metric-evidence slice: compile every Phase 1 signal evaluation into an immutable tenant/incident/run-bound ledger, then verify flat increase/decrease predicates with deterministic `SUPPORTED`, `REFUTED`, or `UNKNOWN` results. Keep runtime dependencies empty and defer persistence, APIs, authorization, Gemini, logs, traces, and change events.

## Parallel analysis

Parallel `gpt-5.6-sol` agents were launched for evidence contracts, verifier semantics, governance, and synthesis. Some agents inspected the read-only `EnterpriseRAG_live` audit repository instead of the independent repository and proposed unrelated RAGAS/Pydantic contracts. Those outputs were rejected as untrusted cross-repository drift. The verifier specialist that inspected the absolute independent-repository path identified useful edge cases: global margin semantics, forged public dataclasses, context-gate leakage, zero score at a zero threshold, contradictory duplicate predicates, empty composition, and complete three-valued traces. ADR 0005 resolves each explicitly.

## Planned experiment

Use synthetic Phase 1 results to prove:

- one evidence entry per canonical signal evaluation;
- a fixed content-ID vector and sensitivity to every committed field;
- rejection of forged or duplicate baseline structures;
- exact threshold, sign, zero-shift, missing, insufficient, weak, context, and causal behavior;
- complete `ALL`/`ANY` truth tables without short-circuit trace loss;
- byte-identical canonical JSON and no sidecar/path/label/secret leakage.

## Expected failure modes

- Treating the baseline's global ranking margin as a per-signal causal verdict.
- Allowing a hypothesis to choose a weaker threshold than the frozen evidence policy.
- Exposing foreign-run evidence during a context mismatch.
- Treating zero shift as both increase and decrease when the policy threshold is zero.
- Accepting opposite predicates for one signal and creating an `ANY` tautology.
- Trusting manually constructed Phase 1 dataclasses without checking cross-field invariants.
- Hashing `repr`, locale-dependent floats, or unordered collections.

## Evidence

Implementation, validation, review, and commit evidence are pending. No credentials, external service, model, database, dataset download, remote, or push is required for this phase.

## Next question

After deterministic evidence and verification are stable, which bounded telemetry type should extend the ledger first without weakening tenant/run isolation or replay guarantees?
