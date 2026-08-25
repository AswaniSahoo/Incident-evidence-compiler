# 0019 — Expose the baseline ranking in the investigation report

- Status: proposed
- Date: 2026-08-23
- Deciders: Aswani
- Supersedes: none
- Related: 0002 (the baseline emits ranked suspicion or abstention, never a causal claim),
  0013 (control plane + worker), 0017 and 0018 (the live demos that made this gap concrete)

## Context

The deterministic baseline is the system's most accurate component — on RE2-OB it reaches Top-1
0.767 against the verifier-gated LLM arm's 0.156 — yet the HTTP API exposes only the *verified
hypothesis*, never the ranking. Both live demos made this concrete: the baseline ranked the faulty
signal first by a wide margin, but the only way to see it was a throwaway inspection script.
Devlogs 0012 and 0013 both close on exactly this question.

The ranking already exists at runtime. The worker computes
`baseline = rank_metric_shifts(window, telemetry, policy)` (`application/worker.py`) to build the
evidence ledger, then discards it. `BaselineResult` is either a `BaselineRanking` (policy, per-signal
evaluations, candidates sorted by descending `suspicion_score`, and the lead margin) or a
`BaselineAbstention` (a reason plus the top/second scores). Both are derived entirely from ingested
telemetry: signal keys, robust medians, and scores — **no fault labels, no ground truth, no model
text**, so the artifact is leakage-safe under the same tenant/run scoping the report endpoint
already enforces.

## Decision

Persist the baseline result at report time and expose it as an **additive, leakage-safe** field on
the report endpoint, without touching the frozen verification schema.

1. **A `baseline-ranking.v1` serializer.** Serialize `BaselineResult` to JSON: the result kind, the
   policy, and either the ranked candidates (signal key, suspicion score, signed score, pre/post
   medians, scale) or the abstention (reason, top/second score). Content-derived from telemetry
   only; nothing label-bearing is included.

2. **Additive, nullable persistence — the verification payload is untouched.** `ReportRecord` gains
   an optional `baseline_payload: str | None`; the reports table gains a nullable `baseline_payload`
   column (an additive migration; existing rows read back `NULL`). The verification `payload` and its
   `metric-hypothesis-verification.v1` schema do not change, so every existing consumer of that
   payload — replay, the evaluation harness — is unaffected by construction.

3. **Additive API.** The report endpoint returns a new sibling field `baseline_ranking` alongside
   `report` (`null` for a report that predates this change). Clients that ignore unknown fields are
   unaffected; there is no verification-schema version bump.

4. **The worker threads the value it already has.** The `baseline` computed for the ledger is
   serialized and set on the `ReportRecord` — one serialize call and one field, no new pipeline
   stage and no new external call.

## Consequences

- The API surfaces the system's most accurate component; the demo no longer needs an out-of-band
  script to show what the baseline found. Closes the open question in devlogs 0012 and 0013.
- One additive, nullable DB migration. `ReportRecord`, the in-memory and Postgres report
  repositories, the new serializer, the worker, and the report endpoint each change, each with a
  test. The verification schema and its consumers do not change.
- Leakage-safe by construction (scores/medians only, tenant/run-scoped); no new runtime dependency;
  the hermetic gate is unchanged except for the new tests.

## Alternatives considered

- **Fold the ranking into the verification payload (schema v2)** — rejected. It bumps the frozen
  `metric-hypothesis-verification.v1` and ripples into replay and the evaluation harness for no
  benefit over an additive sibling field.
- **A separate `GET /investigations/{id}/ranking` endpoint** — rejected for v1. A second route and
  round-trip for data the report reader already wants in hand; a sibling field is simpler and there
  is one obvious consumer.
- **Recompute on read** — rejected. Telemetry is not retained after the run, so the ranking must be
  persisted at report time; recomputation is impossible without re-ingesting.
