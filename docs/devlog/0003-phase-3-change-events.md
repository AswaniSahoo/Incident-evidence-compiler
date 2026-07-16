# Phase 3: Change Events Without Blame

- Date: 2026-07-17
- Status: Complete

## Problem

A metric-only ledger can say a signal shifted but not that anything changed
around it. Operators asking "did a deployment land right before this broke?"
need change events as first-class evidence. The danger is that pairing a change
with a shift invites a causal story the evidence cannot support.

## First principle

Record change events and their timing as descriptive evidence, and verify only
temporal co-occurrence. Whether a change caused an incident is not recoverable
from the fact that it happened nearby, so the verifier must never assert it.

## Alternatives considered

- **Persistence (PostgreSQL) next.** Rejected as premature: it adds the first
  heavy infrastructure dependency and a migration surface while the evidence
  model is still growing, so it would lock in a schema too early.
- **The Gemini model-provider boundary next.** Deferred: its value is thin
  until an orchestration layer feeds it evidence, and the verifier that would
  constrain it is better exercised by broadening evidence first.
- **Traces or logs as the telemetry type.** Traces largely duplicate the metric
  shift logic; logs carry the largest untrusted-text parsing surface. Change
  events are the most bounded shape and best test the descriptive-not-causal
  boundary.

## Decision and trade-offs

Add a bounded change-event telemetry contract, a tenant/incident/run-bound
change-event evidence ledger with content-bound IDs, a restricted co-occurrence
hypothesis, a deterministic tri-state verifier, and canonical leakage-safe
serialization. Reuse the Phase 2 verdict, semantics, and composition enums;
keep a distinct `ChangeUnknownReason` vocabulary and a separate ledger schema so
the frozen metric artifacts are untouched. The trade-off accepted in ADR 0006
is the three-valued `REFUTED` rule: a change recorded only outside the asserted
temporal region refutes the assertion, treating the ledger as the authoritative
record of observed changes, while total absence stays `UNKNOWN`.

## Smallest implemented slice

- `domain/changes.py`: `ChangeEventKey`, closed `ChangeKind`, `ChangeEvent`,
  and a bounded, duplicate-free, canonically ordered `ChangeEventLog`.
- `domain/change_evidence.py`: `change-event-ledger.v1`, window-relative
  `ChangePhase` classification, content-bound evidence IDs under a distinct
  domain separator, and deep-reconstruction validation with no silent repair.
- `domain/change_hypotheses.py`: `ChangeCooccurrencePredicate` and
  `ChangeHypothesisDocument` (exact key, kind, and phase constraint; no
  wildcard, negation, or threshold).
- `domain/change_verifier.py`: fixed context -> causal -> evaluate precedence
  and the exact SUPPORTED / REFUTED / UNKNOWN semantics.
- `domain/serialization.py`: `change_ledger_json` and `change_verification_json`
  (`change-cooccurrence-verification.v1`).

## Experiment or failure scenario

Synthetic change logs prove: one canonically ordered entry per event; correct
half-open phase boundaries; a fixed content-ID vector
(`sha256:35b33f12068c901877ca6c6b4b95840db75027d633f1bc4a6733e0a733f399ee`) with
order invariance and sensitivity to every committed field; rejection of forged,
duplicate, mis-ordered, and inconsistent ledgers; fail-closed context and causal
gates that expose no evidence; in-phase presence supported, out-of-phase
presence refuted, total absence unknown; complete `ALL`/`ANY` three-valued
truth tables retaining every child trace; and byte-stable, leakage-bounded JSON.

## Reproducible evidence

Implemented locally without credentials, external services, model calls,
database access, dataset downloads, remote configuration, or push.

- The one independent implementation review returned `APPROVED` with no blocking
  issues; its three non-blocking nits were deliberate parity with the frozen
  Phase 2 input contracts and were not changed. No repeated review was launched.
- `uv sync --locked` resolved eight development/build packages with no runtime
  dependencies.
- Locked compilation passed.
- `uv run --locked python -m unittest discover -s tests -p "test_*.py" -v`
  passed all 172 tests.
- Ruff check and format passed with 37 files formatted.
- Strict mypy passed over 35 source files.
- The full project validator and Kiro agent validation passed.
- `git diff --check` passed and no remote is configured.

Phase 3 decision, contract/ledger, verifier, and validation-evidence commits
land on `phase/03-planning`; the branch's final commit records completion.

## What failed or changed

Early test type-ignore codes were misplaced under strict mypy; the fix was to
type the change-serialization fixtures precisely rather than suppress errors.
The `test_unsupported_phase_fails_closed` fixture moved from phase 3 to phase 4
because phase 3 is now governed.

## Limitations

Co-occurrence is descriptive only and is verified independently of metric
shifts; no cross-signal correlation and no causal inference. Change events carry
no free-text reference in this slice. `REFUTED` trusts the ledger as the
authoritative record of observed changes; genuinely missing telemetry remains
`UNKNOWN`.

## Next question

With metric and change evidence both landed, is the next bounded slice a third
telemetry type, the durable persistence boundary, or the model-provider
boundary that finally exercises the verifier against untrusted proposals?
