# ADR 0005: Phase 2 Evidence Contracts

- Status: Accepted
- Date: 2026-07-16

## Context

Phase 1 produces deterministic metric-shift evaluations but intentionally does not make causal claims. The next smallest useful vertical slice must preserve those evaluations as replayable evidence and verify a restricted hypothesis without adding a model, database, API, or infrastructure dependency.

## Decision

Phase 2 delivers a framework-independent immutable metric-evidence ledger, a restricted descriptive hypothesis document, a deterministic tri-state verifier, and canonical leakage-safe serialization. It uses only the Python 3.12 standard library.

This phase is a metric-evidence vertical slice. Logs, traces, change events, persistence, authorization, Gemini generation, report prose, APIs, queues, and network services remain later work.

## Evidence ledger

`compile_metric_shift_ledger` binds one trusted Phase 1 `BaselineResult` to a `TenantId`, `IncidentId`, `RunId`, and `IncidentWindow`. Binding is provenance, not authorization. Later service boundaries must establish those identifiers before compilation.

The ledger records:

- schema version `metric-evidence-ledger.v1`;
- tenant, incident, and run identifiers;
- the normalized UTC incident window;
- the frozen baseline policy and aggregate ranking/abstention decision;
- exactly one `MetricShiftEvidence` entry for every unique `SignalEvaluation`;
- entries sorted by exact, case-sensitive `SignalKey.value`.

Each entry records the signal key, pre/post point counts, eligibility, scale floors, and—when eligible—the complete candidate replay fields. Ineligible entries contain no invented candidate values. Empty ledgers are valid; duplicate signal keys or internally inconsistent baseline objects are rejected with stable domain errors.

Evidence IDs are deterministic and content-bound. The canonical entry payload includes the schema version, all ledger bindings, UTC window, policy, decision context, signal key, counts, eligibility, and candidate fields. Datetimes use fixed UTC RFC 3339 microseconds ending in `Z`; finite floats use `float.hex()`. The ID is:

```text
sha256:<lowercase hex SHA-256(
  b"incident-evidence-compiler.metric-shift-evidence.v1\\x00"
  + canonical_entry_json
)>
```

The ID therefore identifies evidence in its exact run context rather than deduplicating equal values across tenants or runs.

The compiler validates the public Phase 1 dataclasses before trusting them: unique evaluation keys; eligibility/candidate consistency; candidate/evaluation key, count, and floor agreement; finite replay values; `suspicion_score == abs(signed_score)`; and ranking or abstention fields consistent with the frozen policy. It never silently repairs forged objects.

## Restricted hypotheses

A `HypothesisDocument` contains:

- a non-empty opaque hypothesis identifier;
- the exact tenant, incident, and run binding it targets;
- semantics `DESCRIPTIVE` or `CAUSAL`;
- composition `ALL` or `ANY`;
- between one and 32 `MetricShiftPredicate` values.

A predicate contains a unique non-empty predicate identifier, one exact `SignalKey`, and expected direction `INCREASE` or `DECREASE`. Signal keys must also be unique across the document, so opposite-direction tautologies for one signal are rejected. There is no free text, arbitrary expression, negation, nesting, query language, custom threshold, or executable field.

The verifier always uses `ledger.policy.minimum_score`; a proposal cannot weaken the evidence threshold. The baseline's global ranking and margin are diagnostic context only. They do not suppress an otherwise strong signal-specific descriptive observation and never establish root cause.

## Exact verification semantics

Gate precedence is fixed:

1. If tenant, incident, or run differs, every predicate and the document return `UNKNOWN` with `CONTEXT_MISMATCH`; no evidence ID or observed value is exposed.
2. If semantics are `CAUSAL`, every predicate and the document return `UNKNOWN` with `CAUSAL_CLAIM_NOT_VERIFIABLE`; no descriptive score is relabeled as causal evidence.
3. If the signal is absent, return `UNKNOWN` with `SIGNAL_NOT_FOUND`.
4. If the signal is ineligible, return `UNKNOWN` with `INSUFFICIENT_EVIDENCE`.
5. If `signed_score == 0.0`, return `UNKNOWN` with `NO_DIRECTIONAL_SHIFT`, including when the configured minimum score is zero.
6. If `suspicion_score < policy.minimum_score`, return `UNKNOWN` with `WEAK_EVIDENCE`.
7. At or above the inclusive threshold, a matching sign is `SUPPORTED` and the opposite sign is `REFUTED`.

Expected evidence defects produce typed `UNKNOWN`; invalid hypothesis or forged ledger construction produces a stable typed domain error. Public errors never echo identifiers, signal names, paths, raw values, or exception text.

All predicates are evaluated in declaration order without outcome-based short-circuiting. Map `SUPPORTED=true`, `REFUTED=false`, and `UNKNOWN=unknown`:

- `ALL`: any refuted -> refuted; otherwise any unknown -> unknown; otherwise supported.
- `ANY`: any supported -> supported; otherwise any unknown -> unknown; otherwise refuted.

Every predicate result records its predicate ID, verdict, optional reason, observed direction, the frozen threshold, and only authorized evidence IDs. Results expose supporting and contradicting evidence IDs separately and retain unknown child traces even when composition is decisive.

## Serialization and leakage boundary

Canonical serializers emit UTF-8 JSON with sorted object keys, compact separators, explicit schema versions, fixed declaration/canonical array ordering, lowercase hashes, finite floats encoded with `float.hex()`, and one terminal LF. Identical logical inputs produce byte-identical output.

Serialization is an investigation artifact, not an evaluation sidecar. It may contain opaque tenant/incident/run IDs, signal keys, replay numbers, verdicts, and evidence IDs. It must never contain RCAEval source paths, service/fault labels, ground-truth sidecars, prompts, model output, credentials, environment values, arbitrary exception text, or causal/root-cause wording. Custom representations remain bounded and expose only type, counts, schema, and verdict—not identifiers, signal keys, or values.

## Governance and tooling

Phase 2 remains dependency-free at runtime and uses the exact locked Phase 1 toolchain and CI actions. Governance becomes cumulative: Phase 2 requires every Phase 1 artifact plus its own ADR, devlog, source modules, and tests. Phase 0 and Phase 1 fixtures continue to validate unchanged. The existing top-level prohibitions for `app`, `data`, `eval`, `infra`, and `migrations` remain in every current phase.

No API key, external service, dataset download, network request, database, or model is required.

## Acceptance criteria

1. Ledger compilation emits one canonically ordered, deeply immutable entry per signal evaluation and rejects inconsistent or duplicate evidence.
2. Evidence IDs match a fixed known vector, are invariant to input ordering, and change when any committed context or evidence field changes.
3. Hypotheses reject empty collections, duplicates, opposite-direction predicates for one signal, unknown types, and more than 32 predicates.
4. Context and causal gates fail closed without exposing evidence; missing, insufficient, zero-direction, and weak evidence yield exact `UNKNOWN` reasons.
5. Inclusive threshold and both sign directions produce exact `SUPPORTED`/`REFUTED` behavior; global baseline ambiguity is proven irrelevant to a signal-specific descriptive predicate.
6. `ALL` and `ANY` pass complete three-valued truth-table and permutation tests while retaining every child result.
7. Canonical ledger and verification JSON are byte-stable, reject non-finite values, and pass canary leakage tests over JSON, repr, errors, and logs.
8. Phase 0, Phase 1, and cumulative Phase 2 governance tests pass with the locked compile, unit-test, Ruff, mypy, validator, Kiro, and Git whitespace gates.
9. One independent implementation review is recorded; concrete blockers are fixed without entering a repeated-review loop.
10. Final Git evidence confirms no RCAEval download, remote, or push.

## Subphase commits

1. `docs: define phase 2 evidence contracts`
2. `feat: add immutable metric evidence ledger`
3. `feat: add deterministic metric verifier`
4. `docs: record phase 2 validation evidence`
