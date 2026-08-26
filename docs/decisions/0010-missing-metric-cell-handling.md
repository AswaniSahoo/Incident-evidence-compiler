# ADR 0010: Missing and non-finite metric cells are gaps, not failures

- Status: Accepted
- Date: 2026-07-17
- Decision owners: Aswani and the project orchestrator

## Context

ADR 0009 acquired RE2-OB and recorded a verified finding: the committed Phase 1 loader parsed
only 19 of 90 real cases, rejecting the rest because real RE2-OB metric CSVs contain empty
(missing) cells and occasional non-finite values. The strict `_number` parser raised
`INVALID_NUMBER` on an empty cell and `NON_FINITE_NUMBER` on a non-finite value, failing the
entire case on the first such cell. ADR 0009 deferred the handling decision to its own slice
because it affects evidence semantics, missing data is not zero.

Relevant domain facts (verified in code):

- `MetricPoint` forbids non-finite values by construction, so a gap cannot be represented as a
  `NaN` point. Representing a gap therefore means the absence of a point at that timestamp.
- `MetricSignal` permits each signal its own strictly increasing timestamps, so one signal may
  skip a timestamp that other signals record.
- The baseline (`_evaluate_signal`) already filters points per window and marks a signal
  ineligible when it has fewer than `minimum_points_per_window` observations in either half, so
  sparse signals degrade to honest abstention rather than a crash or a fabricated value.

## Decision

Treat a missing or non-finite metric cell as a dropped point (a gap) for that one signal at that
timestamp, rather than rejecting the whole case or coercing the value to zero.

1. **Empty metric cell** → drop the point for that column at that row (a gap). Other columns in
   the same row are unaffected.
2. **Non-finite metric cell** (`nan`/`inf`/overflow) → same treatment as empty (drop). A
   non-finite value is not a usable observation and is not representable as a `MetricPoint`.
3. **Non-empty, non-numeric cell** → remains a hard `INVALID_NUMBER` error. This signals a schema
   or format problem, not a missing observation, and must not be silently absorbed.
4. **The `time` column stays strict.** An empty, invalid, or out-of-order timestamp still fails
   the case, because without a valid timestamp no observation can be placed.
5. **Drops are auditable, not silent.** The parser counts dropped cells and exposes
   `dropped_cell_count` on `ParsedCase`, satisfying the no-silent-fallback rule.
6. A fully empty column yields an empty signal (zero points), which the baseline treats as
   ineligible, the signal exists in the schema but carries no usable evidence.

`NON_FINITE_NUMBER` is retained in the error vocabulary but is no longer emitted by metric-cell
parsing.

## Consequences

### Positive

- Real RE2-OB parse coverage rose from 19/90 to 88/90 cases without inventing data: missing and
  non-finite cells become gaps, never zero.
- Evidence semantics stay honest, sparse signals become ineligible via the existing baseline
  gate rather than contributing fabricated zero-valued points.
- The `dropped_cell_count` makes data quality auditable per case.

### Cost / residual

- Two of the 90 cases (`checkoutservice_cpu/2`, `checkoutservice_mem/2`) still fail
  `invalid_timestamp` because their final row has an empty `time` cell. This is a distinct
  trailing-row artifact, not a missing-metric-cell issue, and remains a failure by rule 4. Whether
  to tolerate a trailing row with an empty timestamp is a separate open decision, deferred.
- CI remains hermetic: this decision is exercised by synthetic fixtures and unit tests; the
  90-case parse rate was verified locally against out-of-repo RE2-OB and is not a CI dependency.

## Rejected alternatives

- **Reject the whole case on any missing cell** (prior behavior): discards ~79% of real OB cases
  over sparse cells that the baseline already tolerates. Rejected.
- **Impute missing cells as zero (or forward-fill)**: violates "missing data is not zero" and
  would fabricate observations that bias robust medians. Rejected.
- **Represent gaps as explicit `NaN` points**: forbidden by `MetricPoint` and would push
  non-finite handling into every downstream consumer. Rejected.
