-- 0001_initial.sql — Phase 4 durable persistence boundary.
-- Every table is tenant-scoped; timestamps are timestamptz (domain canonicalizes to UTC).
-- Applied by persistence.migrations.runner, which owns the schema_migrations bookkeeping.

CREATE TABLE investigations (
    id                uuid PRIMARY KEY,
    tenant_id         text NOT NULL,
    incident_id       text NOT NULL,
    run_id            text NOT NULL,
    window_start      timestamptz NOT NULL,
    window_injection  timestamptz NOT NULL,
    window_end        timestamptz NOT NULL,
    status            text NOT NULL,
    idempotency_key   text,
    created_at        timestamptz NOT NULL,
    updated_at        timestamptz NOT NULL
);

-- Idempotent creation: at most one investigation per (tenant, idempotency_key).
CREATE UNIQUE INDEX investigations_tenant_idempotency_key
    ON investigations (tenant_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE jobs (
    id                uuid PRIMARY KEY,
    investigation_id  uuid NOT NULL REFERENCES investigations (id),
    tenant_id         text NOT NULL,
    status            text NOT NULL,
    available_at      timestamptz NOT NULL,
    claimed_by        text,
    claimed_at        timestamptz,
    lease_expires_at  timestamptz,
    attempt_count     integer NOT NULL DEFAULT 0,
    max_attempts      integer NOT NULL,
    created_at        timestamptz NOT NULL,
    updated_at        timestamptz NOT NULL
);

-- Supports the SELECT ... FOR UPDATE SKIP LOCKED claim scan over due, queued jobs.
CREATE INDEX jobs_claim_queued
    ON jobs (available_at, id)
    WHERE status = 'queued';

CREATE TABLE attempts (
    id              uuid PRIMARY KEY,
    job_id          uuid NOT NULL REFERENCES jobs (id),
    tenant_id       text NOT NULL,
    attempt_number  integer NOT NULL,
    worker_id       text NOT NULL,
    started_at      timestamptz NOT NULL,
    finished_at     timestamptz,
    outcome         text,
    error_code      text,
    created_at      timestamptz NOT NULL,
    UNIQUE (job_id, attempt_number)
);

CREATE TABLE evidence (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         text NOT NULL,
    investigation_id  uuid NOT NULL REFERENCES investigations (id),
    run_id            text NOT NULL,
    evidence_id       text NOT NULL,
    ledger_kind       text NOT NULL,
    schema_version    text NOT NULL,
    payload           text NOT NULL,
    created_at        timestamptz NOT NULL,
    UNIQUE (tenant_id, run_id, evidence_id)
);

CREATE INDEX evidence_investigation
    ON evidence (tenant_id, investigation_id);

CREATE TABLE reports (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    investigation_id  uuid NOT NULL UNIQUE REFERENCES investigations (id),
    tenant_id         text NOT NULL,
    run_id            text NOT NULL,
    schema_version    text NOT NULL,
    payload           text NOT NULL,
    created_at        timestamptz NOT NULL
);

CREATE TABLE audit (
    id                bigserial PRIMARY KEY,
    tenant_id         text NOT NULL,
    investigation_id  uuid,
    actor             text NOT NULL,
    action            text NOT NULL,
    detail            text,
    occurred_at       timestamptz NOT NULL
);

CREATE INDEX audit_investigation
    ON audit (tenant_id, investigation_id);
