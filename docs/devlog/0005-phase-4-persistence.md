# Devlog 0004 — Phase 4: durable persistence boundary

Status: implemented and independently reviewed on branch `phase/04-persistence` (not yet
merged to `main`). Hermetic locked gate green: `ruff`, `ruff format --check`, and `mypy`
(51 source files) clean; 212 unittest tests OK with 8 skipped (exactly the PostgreSQL
integration tests, so the gate needs no database); `validate_project.py` passes (full)
under Phase 4; `uv sync --locked` resolves. The psycopg/SQL path was then verified against
a live PostgreSQL 16 (see the verification note below).

## Goal

A minimal, tenant-scoped durable persistence boundary (ADR 0011): typed records and
status enums, repository + unit-of-work protocols, in-memory fakes for the hermetic
gate, an async `psycopg` driver, forward-only SQL migrations, and
`SELECT ... FOR UPDATE SKIP LOCKED` job claiming — with domain code untouched and CI
hermetic against the fakes.

## Slices

- Slice 1 (no new dependency): `persistence` package — `records`, `errors`,
  `repositories` protocols, and in-memory fakes with copy-on-write transactional
  isolation. Independently reviewed; full locked gate green.
- Slice 2 (adds `psycopg[binary]==3.3.4`, the first runtime dependency): initial schema
  migration + async migration runner, async psycopg repositories/unit-of-work, and a
  local `docker-compose.yml`. Governance (`validate_project.py`, its tests, phase
  marker) updated to open Phase 4 and allow the approved dependency and a
  `docker-compose.yml` scope exception.
- Slice 3: the two-worker `SKIP LOCKED` race test over two connections.

## Testing strategy

The hermetic locked gate exercises the protocols against the in-memory fakes only.
The psycopg driver, the migration runner, and the two-worker claim race are covered by
opt-in integration tests that `skipUnless(DATABASE_URL)`, run against the compose
PostgreSQL, and are skipped in CI so the gate needs no database, network, or credentials.

## Verification note

Real-database behavior was verified on 2026-07-17: `docker compose up` (PostgreSQL 16)
with `DATABASE_URL` set, then `python -m unittest tests.test_persistence_postgres` — all 8
integration tests pass, including the two-worker `SKIP LOCKED` race. The hermetic gate
still skips these when `DATABASE_URL` is unset, so CI needs no database.

Finding from the run: psycopg's async connection cannot use Windows' default
`ProactorEventLoop`; the integration module selects `WindowsSelectorEventLoopPolicy` only
when `DATABASE_URL` is set (leaving the hermetic gate untouched). On Linux/CI the default
loop works, so this is a Windows-dev concern.
