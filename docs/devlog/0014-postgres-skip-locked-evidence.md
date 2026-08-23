# Devlog 0014 — Postgres SKIP LOCKED durability evidence

Status: verification run on `main` (no code change). The `FOR UPDATE SKIP LOCKED` job-claim
concurrency, previously proven only by the in-memory fake in the hermetic gate, is here
demonstrated against a real PostgreSQL.

## Why

"PostgreSQL-backed queue with leases and `SKIP LOCKED`" is a headline durability claim, but the
hermetic gate deliberately skips the real-database tests (they need `DATABASE_URL`), so the claim
was code-plus-fake — never a recorded real-PG run. For an evaluated setting that rewards "does it
run, would you trust it", a demonstrated concurrency run is worth more than an assertion.

## What was run (2026-08-23, `postgres:16` via docker-compose)

```bash
docker compose up -d
DATABASE_URL="postgresql://iec:iec@localhost:5432/iec" \
  uv run --locked python -m unittest tests.test_persistence_postgres -v
docker compose down -v
```

Result: **8 tests, OK** in 2.4s. The load-bearing ones:

- `test_two_workers_claim_each_job_exactly_once` — the `SELECT … FOR UPDATE SKIP LOCKED` race: two
  concurrent workers claim a pool of jobs with no double-claim and no lost job.
- `test_expired_lease_is_reclaimable` — a crashed worker's lease is reclaimable after it expires.
- `test_claim_returns_each_job_once`, `test_migrations_are_idempotent`,
  `test_evidence_append_is_idempotent`, `test_investigation_create_is_idempotent_by_key`,
  `test_report_put_once_then_conflict`, `test_get_is_tenant_scoped`.

## Note

This suite is opt-in and stays out of the hermetic gate (it needs a database), so CI remains
hermetic and `EXPECTED_CI_RUNS_BY_PHASE` in the validator is unchanged. This devlog records that the
path has actually been exercised, with the exact command to reproduce it.
