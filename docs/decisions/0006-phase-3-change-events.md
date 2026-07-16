# ADR 0006: Phase 3 Change-Event Co-occurrence Evidence

- Status: Accepted
- Date: 2026-07-17

## Context

Phase 2 delivered an immutable metric-evidence ledger, a restricted descriptive
hypothesis, a deterministic tri-state verifier, and canonical leakage-safe
serialization, all standard-library-only. The Phase 2 devlog left one question
open: which bounded telemetry type should extend the ledger first without
weakening tenant/run isolation or replay guarantees?

The next slice adds **change/deployment events**. In real incidents the most
common human question is "did something change right before this broke?" A
system that answers that question descriptively — without asserting that the
change *caused* the incident — is exactly the boundary this project exists to
hold. Change events are also the most bounded telemetry shape available:
discrete, typed, timestamped occurrences rather than continuous series, so the
untrusted-parsing surface stays minimal.

## Decision

Phase 3 delivers a framework-independent, standard-library-only change-event
vertical slice consisting of four artifacts that mirror the Phase 2 structure:

1. a bounded, immutable **change-event telemetry contract**;
2. a tenant/incident/run-bound **change-event evidence ledger** with
   content-bound evidence IDs;
3. a restricted **temporal co-occurrence hypothesis** and a deterministic
   tri-state verifier;
4. **canonical leakage-safe serialization** for both new artifacts.

This slice verifies change-event co-occurrence **independently of metric
shifts**. Joining a deployment to a metric shift into a single "the deploy broke
the service" narrative is the causal step this project refuses. The verifier
answers only the descriptive question: *a change of a given kind to a given
target occurred in a given temporal region of this run's incident window.*

Persistence, APIs, authorization, Gemini, logs, and traces remain later work.
No dependency, network, dataset, database, or model is added.

## Change-event telemetry contract

New module `domain/changes.py`:

- `ChangeEventKey(value: str)` — a frozen, non-empty opaque key identifying the
  changed component, analogous to `SignalKey`. It is opaque telemetry, never a
  human service or fault label.
- `ChangeKind` — a closed `StrEnum`: `DEPLOYMENT`, `CONFIGURATION`, `ROLLBACK`,
  `SCALING`, `FEATURE_FLAG`. No free text, no open category.
- `ChangeEvent` — frozen dataclass of `(event_key, kind, occurred_at)`.
  `occurred_at` is validated and normalized to aware UTC via the existing
  `to_utc`.
- `ChangeEventLog` — an immutable, canonically ordered collection of
  `ChangeEvent`, bounded by `MAX_CHANGE_EVENTS` (proposed `512`). An empty log
  is valid. Events are ordered by `(occurred_at, kind.value, event_key.value)`.
  Two events sharing all three fields are indistinguishable and rejected as a
  duplicate with a stable domain error; the contract never invents dedup or
  repair semantics.

There is no free-text version/ref field in this slice. If report rendering later
needs an opaque change reference, it is added then with its own justification.

## Change-event evidence ledger

New module `domain/change_evidence.py`, schema version
`change-event-ledger.v1`, kept separate from the frozen metric ledger so no
existing content ID or serialization changes.

`compile_change_event_ledger(tenant_id, incident_id, run_id, window,
change_log)` binds one validated `ChangeEventLog` to a `TenantId`,
`IncidentId`, `RunId`, and `IncidentWindow`. Binding is provenance, not
authorization.

Each retained event becomes one `ChangeEventEvidence` entry recording:

- the content-bound `EvidenceId`;
- `event_key`, `kind`, `occurred_at`;
- a deterministic window-relative `ChangePhase`:
  - `BEFORE_WINDOW`: `occurred_at < start`
  - `PRE_INJECTION`: `start <= occurred_at < injection`
  - `POST_INJECTION`: `injection <= occurred_at < end`
  - `AFTER_WINDOW`: `occurred_at >= end`

All submitted events are retained and classified; out-of-window events are
never silently dropped. Entries are ordered by
`(occurred_at, kind.value, event_key.value)`.

Evidence IDs are deterministic and content-bound, reusing the Phase 2 scheme
with a new domain separator:

```text
sha256:<lowercase hex SHA-256(
  b"incident-evidence-compiler.change-event-evidence.v1\x00"
  + canonical_entry_json
)>
```

The canonical entry payload includes the schema version, all three bindings,
the UTC window (RFC 3339 microseconds ending in `Z`), the event key, the kind,
the UTC `occurred_at`, and the derived phase. The ID therefore identifies a
change observation in its exact run context, never deduplicating equal changes
across tenants or runs.

`validate_change_event_ledger(value)` deeply reconstructs the ledger, re-derives
every phase and content ID, and rejects forged, duplicate, mis-ordered, or
internally inconsistent input with a stable `InvalidChangeEventLedgerError`. It
never repairs forged state.

## Restricted co-occurrence hypothesis

New module `domain/change_hypotheses.py`, reusing `HypothesisSemantics` and
`HypothesisComposition` from Phase 2.

- `ChangePhaseConstraint` — a `StrEnum`: `WITHIN_WINDOW`, `PRE_INJECTION`,
  `POST_INJECTION`.
- `ChangeCooccurrencePredicate(predicate_id, event_key, kind, phase_constraint)`
  — one exact target, one exact kind, one temporal region. No wildcards, no
  free text, no negation, no threshold, no executable field.
- `ChangeHypothesisDocument` — bound to an exact tenant/incident/run, carrying
  `semantics`, `composition`, and 1..32 predicates with unique
  `predicate_id`s. Predicates over the same key/kind with different constraints
  are allowed (they are not tautological); only duplicate identifiers are
  rejected. `validate_change_hypothesis_document` deeply reconstructs and
  rejects malformed input with `InvalidChangeHypothesisError`.

## Exact verification semantics

New module `domain/change_verifier.py`. Reuses `VerificationVerdict`. Uses a
`ChangeUnknownReason` enum (`CONTEXT_MISMATCH`,
`CAUSAL_CLAIM_NOT_VERIFIABLE`, `CHANGE_NOT_OBSERVED`) kept separate from the
metric verifier's `UnknownReason` so the frozen Phase 2 verifier and serializer
are untouched.

Gate precedence is fixed:

1. If tenant, incident, or run differs, every predicate and the document return
   `UNKNOWN` with `CONTEXT_MISMATCH`; no evidence ID is exposed.
2. If semantics are `CAUSAL`, every predicate and the document return `UNKNOWN`
   with `CAUSAL_CLAIM_NOT_VERIFIABLE`; no change observation is relabeled as a
   cause.
3. Otherwise each predicate is evaluated against the ledger's recorded change
   evidence for its exact `(event_key, kind)`:
   - **No matching `(event_key, kind)` event exists anywhere in the ledger ->
     `UNKNOWN` with `CHANGE_NOT_OBSERVED`.** Absence of a change record is not
     proof the change did not happen; telemetry may be incomplete.
   - **At least one matching event satisfies the phase constraint ->
     `SUPPORTED`**, listing the satisfying evidence IDs as supporting.
   - **Matching events exist but none satisfy the phase constraint ->
     `REFUTED`**, listing the incompatible-timing evidence IDs as contradicting.

Phase-constraint satisfaction: `WITHIN_WINDOW` is satisfied by `PRE_INJECTION`
or `POST_INJECTION`; `PRE_INJECTION` and `POST_INJECTION` are satisfied only by
their exact phase.

All predicates are evaluated in declaration order without outcome-based
short-circuiting. Composition reuses the Phase 2 three-valued rules exactly:

- `ALL`: any refuted -> refuted; else any unknown -> unknown; else supported.
- `ANY`: any supported -> supported; else any unknown -> unknown; else refuted.

Each predicate result records its predicate id, verdict, optional reason, the
asserted phase constraint, and only authorized supporting/contradicting evidence
ids. The document exposes supporting and contradicting ids separately and
retains every child trace even when composition is decisive. Expected evidence
defects produce typed `UNKNOWN`; invalid hypothesis or forged ledger
construction produces a stable typed domain error. Public errors never echo
identifiers, keys, kinds, timestamps, paths, raw values, or exception text.

### Trust assumption behind `REFUTED` (key review point)

`REFUTED` treats the ledger as the authoritative record of *observed* changes
for this run: if the only recorded `(event_key, kind)` events fall outside the
asserted region, the temporal assertion is contradicted by positive evidence of
the change occurring at an incompatible time. This mirrors how the metric
verifier trusts the recorded candidate as the authoritative observation for a
signal. Total absence stays `UNKNOWN`, preserving "unknown is distinct from
false." The alternative — treating any absence, including phase-specific
absence, as `UNKNOWN` (a two-valued SUPPORTED/UNKNOWN predicate) — is more
conservative but never yields `REFUTED`. This ADR proposes the first model and
flags the choice for explicit approval.

## Serialization and leakage boundary

Extend `domain/serialization.py` with `change_ledger_json` and
`change_verification_json`, schema `change-cooccurrence-verification.v1`. Both
follow the frozen canonical rules: UTF-8, sorted keys, compact separators,
explicit schema version, fixed ordering, lowercase hashes, RFC 3339 microsecond
`Z` timestamps, one terminal LF, byte-identical output for identical input.

The artifacts may contain opaque tenant/incident/run ids, change event keys,
change kinds, phases, UTC timestamps, verdicts, and evidence ids. They must
never contain RCAEval source paths, service/fault ground-truth labels,
ground-truth sidecars, prompts, model output, credentials, environment values,
arbitrary exception text, or causal/root-cause wording. New dataclasses use
`repr=False` with bounded `__repr__` exposing only type, counts, schema, and
verdict.

## Governance and tooling

Governance stays cumulative. `scripts/validate_project.py` gains a `3` entry in
`PHASE_REQUIRED_FILES` (this ADR, the Phase 3 devlog, the four new source
modules, and the new tests), plus `EXPECTED_CI_RUNS_BY_PHASE[3]` and
`REQUIRED_ACTIONS_BY_PHASE[3]` reusing the Phase 1 locked sets. Moving
`PROJECT_CONTEXT.md` to "Phase 3" and adding the governance entry happen in the
same commit so the phase gate never observes an unsupported phase. Phase 0/1/2
fixtures and the `app`/`data`/`eval`/`infra`/`migrations` prohibitions remain
unchanged. Runtime stays standard-library-only on the exact locked toolchain.

## Acceptance criteria

1. The change-event contract validates and UTC-normalizes events, enforces the
   `MAX_CHANGE_EVENTS` bound, rejects duplicates and non-`StrEnum`/malformed
   fields, and canonically orders a log; an empty log is valid.
2. Ledger compilation emits one immutable, canonically ordered entry per event
   with a correct window-relative phase, and rejects forged, duplicate,
   mis-ordered, or inconsistent input with stable errors.
3. Change evidence IDs match a fixed known vector, are invariant to input
   ordering, and change when any committed context, event, or phase field
   changes.
4. Context and causal gates fail closed without exposing evidence; total
   absence yields `CHANGE_NOT_OBSERVED`; in-phase presence yields `SUPPORTED`;
   out-of-phase presence yields `REFUTED` (pending the trust-assumption
   approval above).
5. `ALL` and `ANY` pass complete three-valued truth-table and permutation tests
   while retaining every child trace.
6. Canonical change-ledger and change-verification JSON are byte-stable and
   pass canary leakage tests over JSON, repr, errors, and logs.
7. Phase 0/1/2 and cumulative Phase 3 governance tests pass under the locked
   compile, unit-test, Ruff, format, mypy, validator, Kiro, and Git whitespace
   gates.
8. One independent implementation review is recorded; concrete blockers are
   fixed without entering a repeated-review loop.
9. Final Git evidence confirms no dataset download, remote, or push.

## Subphase commits

1. `docs: define phase 3 change-event contracts` (this ADR, accepted)
2. `feat: add change-event telemetry contract and evidence ledger`
3. `feat: add deterministic change co-occurrence verifier`
4. `docs: record phase 3 validation evidence`

## Open question for approval

The one semantic decision that needs your explicit sign-off is the **`REFUTED`
trust assumption** in the verification section: do you accept out-of-phase
presence as `REFUTED` (three-valued, proposed), or do you prefer the
conservative two-valued model where only presence-in-phase is `SUPPORTED` and
every absence is `UNKNOWN`? Everything else follows the accepted Phase 2
patterns.
