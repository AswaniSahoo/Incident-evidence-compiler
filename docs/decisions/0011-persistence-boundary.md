# ADR 0011: Durable persistence boundary (Phase 4)

- Status: Accepted
- Date: 2026-07-17
- Decision owners: Aswani and the project orchestrator

## Context

Phases 0–3 produced a standard-library-only domain (`src/incident_evidence_compiler/domain/`)
with typed identifiers, an immutable content-addressed metric-evidence ledger, a separate
change-event ledger, deterministic tri-state verifiers, and canonical leakage-safe
serialization. There is still no I/O: `pyproject.toml` declares `dependencies = []`, and the
locked gate runs entirely against synthetic fixtures and deterministic fakes.

Phase 4 (MASTER-PLAN, Days 2–3) introduces the durable source of truth and the initial job
queue in PostgreSQL: a minimal schema (investigations, jobs, attempts, evidence, reports,
audit), typed repository protocols with in-memory fakes, an async `psycopg` driver, a
migrations runner, and `SELECT … FOR UPDATE SKIP LOCKED` job claiming with a two-worker race
test.

Two standing constraints shape this phase:

- **Domain independence** (engineering steering): domain code must not depend on databases,
  drivers, or frameworks. The dependency direction is one-way — persistence may import
  `domain`; `domain` must never import persistence.
- **Hermetic CI** (Phases 0–3 precedent, ADR 0009): the locked test gate must not require a
  live database, network, or credentials. It runs against fakes only.

This ADR also crosses two approval gates from the workflow steering: it defines the **schema**
and adds the project's **first runtime dependency**.

## Decision

### 1. New top-level package `persistence`

A third top-level package `src/incident_evidence_compiler/persistence/`, sibling to `domain`
and `evaluation`:

```
persistence/
  __init__.py          # public surface: records, enums, errors, protocols
  records.py           # frozen typed row records + status StrEnums (stdlib only)
  errors.py            # persistence-boundary typed errors (stable codes)
  repositories.py      # repository Protocols + UnitOfWork Protocol (stdlib only)
  memory.py            # in-memory fakes implementing the protocols (stdlib only)
  postgres/            # psycopg driver — imported only where a DB is used
    __init__.py
    unit_of_work.py    # async psycopg UnitOfWork + repositories
    queue.py           # SKIP LOCKED claim + lease
  migrations/
    0001_initial.sql   # DDL
    runner.py          # ordered apply + schema_migrations bookkeeping
```

`records.py`, `errors.py`, `repositories.py`, and `memory.py` are standard-library only and
reference existing domain types (`TenantId`, `IncidentId`, `RunId`, `EvidenceId`, `CaseId`,
`IncidentWindow`). Only `persistence.postgres.*` imports `psycopg`. Nothing opens a connection
at import time (engineering steering).

### 2. Minimal schema (proposed DDL shape)

All tables carry `tenant_id text NOT NULL`; every repository query is tenant-scoped. Times are
`timestamptz` (domain canonicalizes to UTC). Identifier text columns store the validated
identifier `value`. Serialized domain artifacts are stored as canonical JSON `text` (the domain
already emits canonical leakage-safe JSON), with a `schema_version` column alongside.

- **investigations** — one row per accepted request.
  `id uuid PK`, `tenant_id`, `incident_id text`, `run_id text`,
  `window_start/window_injection/window_end timestamptz`,
  `status text` (`pending|running|succeeded|failed|cancelled`),
  `idempotency_key text NULL`, `created_at`, `updated_at`.
  Unique `(tenant_id, idempotency_key)` where `idempotency_key IS NOT NULL` → idempotent creation.

- **jobs** — the claimable queue (one active job per investigation stage).
  `id uuid PK`, `investigation_id uuid FK`, `tenant_id`,
  `status text` (`queued|claimed|running|succeeded|failed|cancelled`),
  `available_at timestamptz`, `claimed_by text NULL`, `claimed_at timestamptz NULL`,
  `lease_expires_at timestamptz NULL`, `attempt_count int`, `max_attempts int`,
  `created_at`, `updated_at`.
  Partial index `(available_at, id) WHERE status = 'queued'` for the claim scan.

- **attempts** — append-only execution history per job (retry/audit).
  `id uuid PK`, `job_id uuid FK`, `tenant_id`, `attempt_number int`, `worker_id text`,
  `started_at`, `finished_at timestamptz NULL`,
  `outcome text NULL` (`succeeded|failed|timeout|cancelled`),
  `error_code text NULL` (stable typed code — never a raw message), `created_at`.
  Unique `(job_id, attempt_number)`.

- **evidence** — persisted ledger entries, content-addressed.
  `id uuid PK`, `tenant_id`, `investigation_id uuid FK`, `run_id text`,
  `evidence_id text` (the content-bound domain `EvidenceId`),
  `ledger_kind text` (`metric|change`), `schema_version text`, `payload text` (canonical JSON),
  `created_at`.
  Unique `(tenant_id, run_id, evidence_id)` → idempotent append; enforces same-tenant/same-run.

- **reports** — the replayable incident report, one per investigation.
  `id uuid PK`, `investigation_id uuid FK`, `tenant_id`, `run_id text`,
  `schema_version text`, `payload text` (canonical JSON), `created_at`.
  Unique `(investigation_id)`.

- **audit** — append-only, sanitized event log.
  `id bigserial PK`, `tenant_id`, `investigation_id uuid NULL`, `actor text`, `action text`,
  `detail text NULL` (sanitized JSON — never prompt bodies, secrets, or PII), `occurred_at`.

### 3. Typed records + boundary errors (no anonymous dicts)

`records.py` exposes frozen slotted dataclasses (`InvestigationRecord`, `JobRecord`,
`ClaimedJob`, `AttemptRecord`, `EvidenceRecord`, `ReportRecord`, `AuditRecord`) plus status
`StrEnum`s. `errors.py` exposes stable typed errors mirroring the domain convention (a
`PersistenceError` base with a `ClassVar code`, e.g. `IdempotencyConflictError`,
`RecordNotFoundError`, `LeaseLostError`, `MigrationError`). No raw driver exceptions cross the
boundary.

### 4. Repository + UnitOfWork protocols

`repositories.py` defines `typing.Protocol`s: `InvestigationRepository`, `JobQueue`,
`AttemptRepository`, `EvidenceRepository`, `ReportRepository`, `AuditLog`, and a `UnitOfWork`
async context manager that yields the repositories and commits on clean exit / rolls back on
error. All methods are `async`. Both the in-memory fake and the psycopg driver satisfy the same
protocols, so callers (the future worker/control plane) never import a concrete backend.

### 5. Async `psycopg` — the first runtime dependency

Add `psycopg` (v3, async) as the first entry in `pyproject.toml` `dependencies`, resolved and
pinned exactly into `uv.lock` via `uv add` **at the start of Slice 2** (not now, and not for
future phases). Binary vs. source build (`psycopg[binary]`) to be chosen at add time and
recorded. Migrations are plain `.sql` applied in order by a small runner that records applied
versions in a `schema_migrations` table.

### 6. `SELECT … FOR UPDATE SKIP LOCKED` job claiming

A worker claims work in one transaction:

```sql
SELECT id FROM jobs
WHERE status = 'queued' AND available_at <= now()
ORDER BY available_at, id
FOR UPDATE SKIP LOCKED
LIMIT 1;
-- then, same tx:
UPDATE jobs SET status = 'claimed', claimed_by = $worker,
    claimed_at = now(), lease_expires_at = now() + $lease, attempt_count = attempt_count + 1
WHERE id = $id;
```

`SKIP LOCKED` lets concurrent workers pass over rows already locked by a peer instead of
blocking, so N workers claim N distinct jobs without a double-claim. A lease
(`lease_expires_at`) lets a crashed worker's job be reclaimed after expiry.

### 7. Testing strategy — hermetic gate, opt-in integration

- **Hermetic (always, in CI + the locked gate):** all protocol semantics are tested against the
  in-memory fakes — idempotent creation, tenant isolation (cross-tenant reads return not-found),
  idempotent evidence append, single-claim semantics, lease expiry, FIFO-by-`available_at`.
- **Integration (opt-in, skipped when `DATABASE_URL` is unset):** the psycopg driver, the
  migrations runner, and the **two-worker race test** (two real connections claiming from a pool
  of N jobs, asserting each job is claimed exactly once) run only against a real Postgres started
  via a committed `docker-compose.yml`. These tests `skipUnless(os.environ.get("DATABASE_URL"))`,
  so the locked gate stays hermetic and credential-free.

The true `SKIP LOCKED` race cannot be reproduced against an in-memory fake with real fidelity;
keeping that test as opt-in integration is the deliberate cost of a hermetic gate.

### 8. Slice order (test-first, one vertical slice each)

1. **Slice 1 (no new deps):** records + enums + errors + protocols + in-memory fakes + hermetic
   tests. Domain unchanged; `dependencies` still `[]`.
2. **Slice 2 (adds psycopg):** `0001_initial.sql` + migrations runner + async psycopg UnitOfWork
   and repositories + `docker-compose.yml`; integration tests gated on `DATABASE_URL`.
3. **Slice 3:** `SKIP LOCKED` claim + lease + two-worker race test (integration, gated).

Each slice ends with the locked gate green and is reviewed by a separate agent before it is
accepted.

## Consequences

### Positive

- The worker/control-plane code in later phases depends only on protocols, so it is unit-testable
  against fakes with no database.
- Domain independence and hermetic CI are both preserved: the only DB-touching code lives under
  `persistence.postgres` and is exercised only by opt-in integration tests.
- Idempotency and tenant isolation are enforced structurally (unique constraints + tenant-scoped
  queries), matching the product invariant that every accepted claim resolves to same-tenant,
  same-run evidence.

### Cost

- `psycopg` becomes the first runtime dependency; the project is no longer pure standard library.
- The most important correctness property (the claim race) is verified only in opt-in
  integration, not in the hermetic gate. This is an explicit, documented trade-off.
- Storing serialized ledgers/reports as canonical JSON `text` favors replay fidelity and the
  existing serialization contract over relational queryability of evidence internals.

## Approvals (resolved 2026-07-17)

Aswani approved all three open questions:

1. **Schema shape** — the six tables and their columns/constraints above are accepted as
   the minimal set for v1.
2. **Dependency** — `psycopg[binary]` (v3, async) is accepted as the first runtime
   dependency, pinned exactly to `psycopg[binary]==3.3.4` in `pyproject.toml` and locked
   to `psycopg==3.3.4` / `psycopg-binary==3.3.4` in `uv.lock`. The project validator was
   made phase-aware so this dependency is allowed only from Phase 4 onward; Phases 1–3
   still require an empty runtime dependency set.
3. **Race-test placement** — the two-worker race test and all psycopg tests are opt-in
   integration tests gated on `DATABASE_URL`, skipped in the hermetic gate.

## Verification (2026-07-17)

Implemented in three reviewed slices on `phase/04-persistence`:

- Slice 1 (no dependency): records, errors, repository/unit-of-work protocols, and
  in-memory fakes; independently reviewed.
- Slice 2 (adds psycopg): `0001_initial.sql`, the async migration runner, the async
  psycopg repositories/unit-of-work, and `docker-compose.yml`; governance opened to
  Phase 4.
- Slice 3: the two-worker `SELECT ... FOR UPDATE SKIP LOCKED` race test.

Hermetic locked gate: `ruff check`, `ruff format --check`, and `mypy` (51 source files)
clean; `python -m unittest` runs 212 tests, OK with 8 skipped — the skips are exactly the
PostgreSQL integration tests, so the gate stays hermetic without a database; the project
validator passes (full) under Phase 4; `uv sync --locked` resolves.

Real-database verification (2026-07-17): the opt-in integration tests were run against
PostgreSQL 16 via `docker compose up` with `DATABASE_URL` set. All 8 tests pass —
migration idempotency, investigation idempotency, tenant-scoped reads, single-claim and
FIFO claiming, expired-lease reclaim, content-addressed evidence dedupe, one-report
conflict, and the two-worker `SELECT … FOR UPDATE SKIP LOCKED` race (25 jobs, two
concurrent connections, each job claimed exactly once). The SQL path is therefore
verified, not merely written.

Finding from that run: psycopg's async connection cannot use Windows' default
`ProactorEventLoop`; the integration test module selects `WindowsSelectorEventLoopPolicy`
only when `DATABASE_URL` is set, so the hermetic gate is untouched. On Linux/CI the
default loop works, so this is a Windows-dev concern. A known behavioral note is
documented in the driver: the `attempts`/`reports` conflict path aborts the transaction
(safe under the rollback-on-exception unit-of-work; a future savepoint refinement is
possible). Non-blocking follow-ups from review: a migration-runner advisory lock for
concurrent runners, and an index for the expired-lease claim branch if reclaim-scan cost
matters.

## Rejected alternatives

- **Put repository protocols inside `domain`:** would let the framework-independent core carry
  persistence concepts. Rejected; protocols live in the separate `persistence` package.
- **An ORM (SQLAlchemy):** heavier dependency and abstraction than a minimal schema needs;
  obscures the exact `SKIP LOCKED` semantics this phase is meant to demonstrate. Rejected for v1.
- **Redis-backed queue now:** deferred by ADR 0007 (Postgres-only concurrency for v1).
- **A live database in the CI gate:** breaks the hermetic guarantee held since Phase 0. Rejected;
  real-DB tests are opt-in integration.
- **Normalizing evidence/report internals into relational columns:** premature; the canonical
  JSON contract already exists and must round-trip for replay. Rejected for v1.
