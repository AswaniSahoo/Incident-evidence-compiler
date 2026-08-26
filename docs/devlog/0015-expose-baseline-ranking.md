# Devlog 0015, Expose the baseline ranking in the report (ADR 0019)

Status: implemented and **accepted** on `main`. Additive and nullable throughout, the frozen
`metric-hypothesis-verification.v1` schema and every consumer of it are untouched.

## Problem

The deterministic baseline is the system's most accurate component (RE2-OB Top-1 0.767), but the
report API exposed only the verified hypothesis. The ranking was computed in the worker to build the
ledger, then discarded; devlogs 0012 and 0013 both closed on exactly this.

## Slices (TDD, each gate-green)

1. **`baseline-ranking.v1` serializer** (`baseline_ranking_json`), ranked candidates or an
   abstention with its reason, hex-float exact, fail-closed on a foreign object; reuses the existing
   `_candidate_payload` / `_policy_payload`.
2. **`ReportRecord.baseline_payload: str | None`**, nullable, defaulted, validated as optional text.
3. **Additive migration `0002_report_baseline_payload.sql`** (`ALTER TABLE reports ADD COLUMN
   baseline_payload text`) plus the Postgres repo columns; the in-memory repo needed no change (it
   stores the record).
4. **The worker threads the already-computed `baseline`** into the report, serialized inside the
   existing fail-closed try block, so a serialization failure stays terminal and leakage-safe.
5. **The report endpoint returns a sibling `baseline_ranking` field** (`null` for a report that
   predates the change). No verification-schema version bump.

## Evidence (2026-08-23)

- Hermetic gate green: **340 tests** (up from 336: serializer ×3, in-memory round-trip, worker
  assertion, endpoint assertion), `ruff`, `ruff format`, strict `mypy` over 89 files, validator full
  pass.
- Postgres integration green against `postgres:16`: **8 tests**, migration `0002` applied and
  `baseline_payload` round-tripped through a real database.
- No new dependency; `pyproject.toml` / `uv.lock` unchanged.

## What changed

The README limitation "the report exposes only the verified hypothesis, not the baseline's ranking"
is removed, it is resolved. The API now surfaces the system's most accurate component, so the demo
no longer needs an out-of-band script to show what the baseline found.
