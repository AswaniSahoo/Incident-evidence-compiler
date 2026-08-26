# Interphase: Publish, Refactor, and Real-Data Grounding

- Date: 2026-07-17
- Status: Complete (bridges Phase 3 → Phase 4)

## Problem

Phases 0–3 were built and verified entirely against synthetic fixtures and were
never public. Before starting Phase 4 (durable persistence), three things had to
happen honestly: publish the accepted history under a license without leaking
local AI-assistant traces, reduce the oversized `evidence.py` so the domain stays
navigable, and confront the real RCAEval RE2 data so persistence and evaluation
are designed against real shapes rather than assumptions. The risk throughout was
committing separately-licensed raw data, or claiming real-data readiness the code
had never demonstrated.

## First principle

Ground claims in verified artifacts and keep separately-licensed data out of the
repository and out of CI. Publication, refactors, and data acquisition must each
be reversible, gate-checked, and recorded; "missing data is not zero" is an
evidence-semantics rule, not a parsing convenience.

## Alternatives considered

- **Push straight into Phase 4 persistence** without touching the real data.
  Rejected: the loader's real-shape assumptions would stay unverified, and the
  MASTER-PLAN risk note flags real-data preprocessing as the most underestimated
  task. Grounding first de-risks Phase 4 and 7.
- **Download RE2-OB into `data/RE2/` inside the repo** and relax the validator.
  Rejected: the validator forbids raw archives/extracted trees anywhere in the
  working tree, independent of `.gitignore`; relaxing it weakens that guarantee
  for a local convenience.
- **Fix real-data parsing by rejecting incomplete cases, or by imputing zeros.**
  Rejected: rejection discards ~79% of real cases the baseline already tolerates;
  zero-imputation fabricates observations and biases robust medians.

## Decision and trade-offs

Four decisions were recorded and executed:

- **ADR 0008 (already accepted):** Apache-2.0. History published to
  `origin` (`AswaniSahoo/Incident-evidence-compiler`); `CLAUDE.md` and
  personal internship details were scrubbed from history before the first push
  and are `.gitignore`d.
- **Refactor:** `evidence.py` (752 lines) split into a focused `evidence/`
  package (`types`, `_identity`, `_ledger`, `_decisions`, `_parsing`) with an
  unchanged public API, a behavior-preserving move verified by the full gate.
- **ADR 0009:** RE2-OB acquired locally under a guardrail, downloaded,
  checksum-verified, stored and extracted **outside** the repository root so the
  validator's no-raw-data guarantee is untouched; never committed; CI stays
  hermetic; RE2-TT sealed, RE2-SS reserved.
- **ADR 0010:** a missing (empty) or non-finite metric cell is a gap, the point
  is dropped for that signal at that timestamp, never coerced to zero. Non-empty
  non-numeric cells still hard-fail `INVALID_NUMBER`; the `time` column stays
  strict; `dropped_cell_count` is exposed on `ParsedCase` for auditability.

The accepted trade-off in ADR 0010 is that sparse signals degrade to honest
abstention through the existing baseline eligibility gate rather than
contributing fabricated points, and that two cases with a truncated final row
remain hard failures by the strict-timestamp rule.

## Smallest implemented slice

- `evidence/` package split (`refactor: split evidence module`, `fc5f057`).
- `.gitignore`: `data/RE2/`, `*.zip`; ADR 0009 (`21bd72e`).
- `evaluation/rcaeval/csv_loader.py`: `_finite_value_or_gap` classifier,
  per-column gap drops with a `dropped_cell_count`, and `ParsedCase.dropped_cell_count`;
  ADR 0010 (`773d39d`).
- `tests/test_rcaeval.py`: error-matrix update plus three new tests
  (gap-drops-not-case, exact dropped-cell count, fully-empty column → empty signal).

## Experiment or failure scenario

RE2-OB was downloaded and verified: size `1191025569` bytes and
`md5:b9e23f8842c404b396ffd2becff15de4`, both an exact match to the pinned
manifest. A local per-case smoke check (out-of-repo, not committed) against the
extracted split established the before/after:

- Before ADR 0010: 19 of 90 cases parsed; 70 failed `invalid_number` (empty
  cells such as `checkoutservice_cpu/1/simple_metrics.csv` lines 181 and 645)
  and 1 failed `non_finite_number`.
- After ADR 0010: 88 of 90 cases parsed. 69 cases contained at least one gap;
  32,129 cells were dropped across the split (max 5,412 in one case).
- Residual: 2 cases (`checkoutservice_cpu/2`, `checkoutservice_mem/2`) still fail
  `invalid_timestamp` because their final row has an empty `time` cell.

## Reproducible evidence

Implemented locally without model calls or external services. The published
history is on `origin/main` at `773d39d`.

- Full gate green after ADR 0010: `compileall`; 176 unit tests pass;
  `ruff check`; `ruff format --check` (42 files); strict `mypy` (40 source files);
  `python scripts/validate_project.py` (full); `git diff --check`.
- The 88/90 real-data parse rate was measured locally against the out-of-repo
  RE2-OB copy and is **not** a CI dependency; CI runs only on synthetic fixtures
  and fakes.
- No raw data, archive, or derived fixture was committed.

## What failed or changed

The committed Phase 1 loader could not parse real RE2-OB at all until ADR 0010,
which is exactly why ADR 0009 required grounding in real shapes before Phase 4.
`NON_FINITE_NUMBER` is retained in the error vocabulary but is no longer emitted
by metric-cell parsing (non-finite is now a gap). PROJECT_CONTEXT's duplicated
"Open decisions" header (a prior edit artifact) was corrected into an
"Accepted (recent)" section plus a single open-decisions list.

## Limitations

Only RE2-OB was acquired; RE2-TT stays sealed and RE2-SS reserved. No sanitized,
label-free fixture derived from real shapes is committed yet, that remains a
deferred slice. Two OB cases remain unparsed pending the trailing-empty-timestamp
decision. The loader change is verified by synthetic tests; the real-data numbers
are local-only.

## Next question

Phase 4 is the durable persistence boundary. The open questions to resolve before
implementation: what is the minimal schema (investigations, jobs, attempts,
evidence, reports, audit), what are the repository protocols and their in-memory
fakes, and does `psycopg` (async) enter now as the first runtime dependency with
`SELECT … FOR UPDATE SKIP LOCKED` job claiming, all while keeping CI hermetic
against fakes and committing no live database dependency into the test gate.
