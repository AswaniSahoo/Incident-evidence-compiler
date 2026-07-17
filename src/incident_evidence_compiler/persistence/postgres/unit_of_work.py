"""Async psycopg repositories, unit of work, and factory.

Each unit of work owns one connection with a manual transaction: work is performed
through the repositories and published with ``commit``; leaving the scope on an
exception rolls back. Every query is tenant-scoped. Raw driver exceptions are mapped to
the typed persistence errors so nothing driver-specific crosses the boundary.

Caveat (differs from the in-memory fake): the ``attempts`` and ``reports`` conflict
paths surface ``IdempotencyConflictError`` from a PostgreSQL ``UniqueViolation``, which
aborts the current transaction. The unit of work rolls back on exception at scope exit,
so this is safe for the normal one-conflict-per-scope usage; a caller that catches the
error and keeps issuing statements on the same unit of work will hit an aborted
transaction. Wrapping those inserts in savepoints is a possible future refinement.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any

import psycopg
from psycopg import AsyncConnection, errors

from ...domain.identifiers import EvidenceId, IncidentId, RunId, TenantId
from ...domain.incidents import IncidentWindow
from ..errors import (
    IdempotencyConflictError,
    InvalidPersistenceRecordError,
    RecordNotFoundError,
)
from ..records import (
    AttemptId,
    AttemptOutcome,
    AttemptRecord,
    AuditRecord,
    ClaimedJob,
    EvidenceRecord,
    InvestigationId,
    InvestigationRecord,
    InvestigationStatus,
    JobId,
    JobRecord,
    JobStatus,
    LedgerKind,
    ReportRecord,
)
from ..repositories import (
    AttemptRepository,
    AuditLog,
    EvidenceRepository,
    InvestigationRepository,
    JobQueue,
    ReportRepository,
    UnitOfWork,
)

_Connection = AsyncConnection[Any]
_ConnectionProvider = Callable[[], _Connection]
_Row = tuple[Any, ...]

_INVESTIGATION_COLS = (
    "id, tenant_id, incident_id, run_id, window_start, window_injection, "
    "window_end, status, idempotency_key, created_at, updated_at"
)
_JOB_COLS = (
    "id, investigation_id, tenant_id, status, available_at, claimed_by, "
    "claimed_at, lease_expires_at, attempt_count, max_attempts, created_at, updated_at"
)
_ATTEMPT_COLS = (
    "id, job_id, tenant_id, attempt_number, worker_id, started_at, "
    "finished_at, outcome, error_code, created_at"
)
_EVIDENCE_COLS = (
    "tenant_id, investigation_id, run_id, evidence_id, ledger_kind, "
    "schema_version, payload, created_at"
)
_REPORT_COLS = "investigation_id, tenant_id, run_id, schema_version, payload, created_at"
_AUDIT_COLS = "tenant_id, investigation_id, actor, action, detail, occurred_at"


def _placeholders(count: int) -> str:
    return ", ".join(["%s"] * count)


def _investigation(row: _Row) -> InvestigationRecord:
    return InvestigationRecord(
        investigation_id=InvestigationId(row[0]),
        tenant=TenantId(row[1]),
        incident=IncidentId(row[2]),
        run=RunId(row[3]),
        window=IncidentWindow(start=row[4], injection=row[5], end=row[6]),
        status=InvestigationStatus(row[7]),
        idempotency_key=row[8],
        created_at=row[9],
        updated_at=row[10],
    )


def _job(row: _Row) -> JobRecord:
    return JobRecord(
        job_id=JobId(row[0]),
        investigation_id=InvestigationId(row[1]),
        tenant=TenantId(row[2]),
        status=JobStatus(row[3]),
        available_at=row[4],
        claimed_by=row[5],
        claimed_at=row[6],
        lease_expires_at=row[7],
        attempt_count=row[8],
        max_attempts=row[9],
        created_at=row[10],
        updated_at=row[11],
    )


def _attempt(row: _Row) -> AttemptRecord:
    return AttemptRecord(
        attempt_id=AttemptId(row[0]),
        job_id=JobId(row[1]),
        tenant=TenantId(row[2]),
        attempt_number=row[3],
        worker_id=row[4],
        started_at=row[5],
        finished_at=row[6],
        outcome=AttemptOutcome(row[7]) if row[7] is not None else None,
        error_code=row[8],
        created_at=row[9],
    )


def _evidence(row: _Row) -> EvidenceRecord:
    return EvidenceRecord(
        tenant=TenantId(row[0]),
        investigation_id=InvestigationId(row[1]),
        run=RunId(row[2]),
        evidence_id=EvidenceId(row[3]),
        ledger_kind=LedgerKind(row[4]),
        schema_version=row[5],
        payload=row[6],
        created_at=row[7],
    )


def _report(row: _Row) -> ReportRecord:
    return ReportRecord(
        investigation_id=InvestigationId(row[0]),
        tenant=TenantId(row[1]),
        run=RunId(row[2]),
        schema_version=row[3],
        payload=row[4],
        created_at=row[5],
    )


def _audit(row: _Row) -> AuditRecord:
    return AuditRecord(
        tenant=TenantId(row[0]),
        investigation_id=InvestigationId(row[1]) if row[1] is not None else None,
        actor=row[2],
        action=row[3],
        detail=row[4],
        occurred_at=row[5],
    )


class _InvestigationRepository:
    def __init__(self, connection: _ConnectionProvider) -> None:
        self._connection = connection

    async def create(self, record: InvestigationRecord) -> InvestigationRecord:
        params = (
            record.investigation_id.value,
            record.tenant.value,
            record.incident.value,
            record.run.value,
            record.window.start,
            record.window.injection,
            record.window.end,
            record.status.value,
            record.idempotency_key,
            record.created_at,
            record.updated_at,
        )
        try:
            async with self._connection().cursor() as cursor:
                if record.idempotency_key is not None:
                    await cursor.execute(
                        f"INSERT INTO investigations ({_INVESTIGATION_COLS}) "
                        f"VALUES ({_placeholders(11)}) "
                        "ON CONFLICT (tenant_id, idempotency_key) "
                        "WHERE idempotency_key IS NOT NULL DO NOTHING "
                        f"RETURNING {_INVESTIGATION_COLS}",
                        params,
                    )
                    inserted = await cursor.fetchone()
                    if inserted is not None:
                        return _investigation(inserted)
                    await cursor.execute(
                        f"SELECT {_INVESTIGATION_COLS} FROM investigations "
                        "WHERE tenant_id = %s AND idempotency_key = %s",
                        (record.tenant.value, record.idempotency_key),
                    )
                    existing = await cursor.fetchone()
                    if existing is None:
                        raise IdempotencyConflictError
                    return _investigation(existing)
                await cursor.execute(
                    f"INSERT INTO investigations ({_INVESTIGATION_COLS}) "
                    f"VALUES ({_placeholders(11)}) RETURNING {_INVESTIGATION_COLS}",
                    params,
                )
                row = await cursor.fetchone()
        except errors.UniqueViolation as exc:
            raise IdempotencyConflictError from exc
        assert row is not None
        return _investigation(row)

    async def get(self, tenant: TenantId, investigation_id: InvestigationId) -> InvestigationRecord:
        async with self._connection().cursor() as cursor:
            await cursor.execute(
                f"SELECT {_INVESTIGATION_COLS} FROM investigations "
                "WHERE id = %s AND tenant_id = %s",
                (investigation_id.value, tenant.value),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RecordNotFoundError
        return _investigation(row)

    async def set_status(
        self, tenant: TenantId, investigation_id: InvestigationId, status: InvestigationStatus
    ) -> InvestigationRecord:
        async with self._connection().cursor() as cursor:
            await cursor.execute(
                "UPDATE investigations SET status = %s, updated_at = now() "
                f"WHERE id = %s AND tenant_id = %s RETURNING {_INVESTIGATION_COLS}",
                (status.value, investigation_id.value, tenant.value),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RecordNotFoundError
        return _investigation(row)


class _JobQueue:
    def __init__(self, connection: _ConnectionProvider) -> None:
        self._connection = connection

    async def enqueue(self, record: JobRecord) -> JobRecord:
        params = (
            record.job_id.value,
            record.investigation_id.value,
            record.tenant.value,
            record.status.value,
            record.available_at,
            record.claimed_by,
            record.claimed_at,
            record.lease_expires_at,
            record.attempt_count,
            record.max_attempts,
            record.created_at,
            record.updated_at,
        )
        try:
            async with self._connection().cursor() as cursor:
                await cursor.execute(
                    f"INSERT INTO jobs ({_JOB_COLS}) "
                    f"VALUES ({_placeholders(12)}) RETURNING {_JOB_COLS}",
                    params,
                )
                row = await cursor.fetchone()
        except errors.UniqueViolation as exc:
            raise IdempotencyConflictError from exc
        assert row is not None
        return _job(row)

    async def claim(
        self, worker_id: str, *, lease: timedelta, now: datetime | None = None
    ) -> ClaimedJob | None:
        if not worker_id.strip():
            raise InvalidPersistenceRecordError
        moment = now if now is not None else datetime.now(UTC)
        lease_expiry = moment + lease
        async with self._connection().cursor() as cursor:
            await cursor.execute(
                "SELECT id FROM jobs "
                "WHERE (status = 'queued' AND available_at <= %s) "
                "OR (status = 'claimed' AND lease_expires_at IS NOT NULL "
                "AND lease_expires_at <= %s) "
                "ORDER BY available_at, id FOR UPDATE SKIP LOCKED LIMIT 1",
                (moment, moment),
            )
            candidate = await cursor.fetchone()
            if candidate is None:
                return None
            await cursor.execute(
                "UPDATE jobs SET status = 'claimed', claimed_by = %s, claimed_at = %s, "
                "lease_expires_at = %s, attempt_count = attempt_count + 1, updated_at = %s "
                f"WHERE id = %s RETURNING {_JOB_COLS}",
                (worker_id, moment, lease_expiry, moment, candidate[0]),
            )
            claimed = await cursor.fetchone()
        assert claimed is not None
        return ClaimedJob(
            job_id=JobId(claimed[0]),
            investigation_id=InvestigationId(claimed[1]),
            tenant=TenantId(claimed[2]),
            worker_id=worker_id,
            lease_expires_at=claimed[7],
            attempt_count=claimed[8],
        )

    async def get(self, tenant: TenantId, job_id: JobId) -> JobRecord:
        async with self._connection().cursor() as cursor:
            await cursor.execute(
                f"SELECT {_JOB_COLS} FROM jobs WHERE id = %s AND tenant_id = %s",
                (job_id.value, tenant.value),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RecordNotFoundError
        return _job(row)

    async def set_status(self, tenant: TenantId, job_id: JobId, status: JobStatus) -> JobRecord:
        async with self._connection().cursor() as cursor:
            await cursor.execute(
                "UPDATE jobs SET status = %s, updated_at = now() "
                f"WHERE id = %s AND tenant_id = %s RETURNING {_JOB_COLS}",
                (status.value, job_id.value, tenant.value),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RecordNotFoundError
        return _job(row)


class _AttemptRepository:
    def __init__(self, connection: _ConnectionProvider) -> None:
        self._connection = connection

    async def record(self, record: AttemptRecord) -> AttemptRecord:
        params = (
            record.attempt_id.value,
            record.job_id.value,
            record.tenant.value,
            record.attempt_number,
            record.worker_id,
            record.started_at,
            record.finished_at,
            record.outcome.value if record.outcome is not None else None,
            record.error_code,
            record.created_at,
        )
        try:
            async with self._connection().cursor() as cursor:
                await cursor.execute(
                    f"INSERT INTO attempts ({_ATTEMPT_COLS}) "
                    f"VALUES ({_placeholders(10)}) RETURNING {_ATTEMPT_COLS}",
                    params,
                )
                row = await cursor.fetchone()
        except errors.UniqueViolation as exc:
            raise IdempotencyConflictError from exc
        assert row is not None
        return _attempt(row)

    async def list_for_job(self, tenant: TenantId, job_id: JobId) -> tuple[AttemptRecord, ...]:
        async with self._connection().cursor() as cursor:
            await cursor.execute(
                f"SELECT {_ATTEMPT_COLS} FROM attempts "
                "WHERE tenant_id = %s AND job_id = %s ORDER BY attempt_number",
                (tenant.value, job_id.value),
            )
            rows = await cursor.fetchall()
        return tuple(_attempt(row) for row in rows)


class _EvidenceRepository:
    def __init__(self, connection: _ConnectionProvider) -> None:
        self._connection = connection

    async def append(self, records: Sequence[EvidenceRecord]) -> tuple[EvidenceRecord, ...]:
        stored: list[EvidenceRecord] = []
        async with self._connection().cursor() as cursor:
            for record in records:
                params = (
                    record.tenant.value,
                    record.investigation_id.value,
                    record.run.value,
                    record.evidence_id.value,
                    record.ledger_kind.value,
                    record.schema_version,
                    record.payload,
                    record.created_at,
                )
                await cursor.execute(
                    f"INSERT INTO evidence ({_EVIDENCE_COLS}) "
                    f"VALUES ({_placeholders(8)}) "
                    "ON CONFLICT (tenant_id, run_id, evidence_id) DO NOTHING "
                    f"RETURNING {_EVIDENCE_COLS}",
                    params,
                )
                inserted = await cursor.fetchone()
                if inserted is not None:
                    stored.append(_evidence(inserted))
                    continue
                await cursor.execute(
                    f"SELECT {_EVIDENCE_COLS} FROM evidence "
                    "WHERE tenant_id = %s AND run_id = %s AND evidence_id = %s",
                    (record.tenant.value, record.run.value, record.evidence_id.value),
                )
                existing = await cursor.fetchone()
                assert existing is not None
                stored.append(_evidence(existing))
        return tuple(stored)

    async def list_for_investigation(
        self, tenant: TenantId, investigation_id: InvestigationId
    ) -> tuple[EvidenceRecord, ...]:
        async with self._connection().cursor() as cursor:
            await cursor.execute(
                f"SELECT {_EVIDENCE_COLS} FROM evidence "
                "WHERE tenant_id = %s AND investigation_id = %s ORDER BY evidence_id",
                (tenant.value, investigation_id.value),
            )
            rows = await cursor.fetchall()
        return tuple(_evidence(row) for row in rows)


class _ReportRepository:
    def __init__(self, connection: _ConnectionProvider) -> None:
        self._connection = connection

    async def put(self, record: ReportRecord) -> ReportRecord:
        params = (
            record.investigation_id.value,
            record.tenant.value,
            record.run.value,
            record.schema_version,
            record.payload,
            record.created_at,
        )
        try:
            async with self._connection().cursor() as cursor:
                await cursor.execute(
                    f"INSERT INTO reports ({_REPORT_COLS}) "
                    f"VALUES ({_placeholders(6)}) RETURNING {_REPORT_COLS}",
                    params,
                )
                row = await cursor.fetchone()
        except errors.UniqueViolation as exc:
            raise IdempotencyConflictError from exc
        assert row is not None
        return _report(row)

    async def get(self, tenant: TenantId, investigation_id: InvestigationId) -> ReportRecord:
        async with self._connection().cursor() as cursor:
            await cursor.execute(
                f"SELECT {_REPORT_COLS} FROM reports "
                "WHERE investigation_id = %s AND tenant_id = %s",
                (investigation_id.value, tenant.value),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RecordNotFoundError
        return _report(row)


class _AuditLog:
    def __init__(self, connection: _ConnectionProvider) -> None:
        self._connection = connection

    async def record(self, record: AuditRecord) -> None:
        params = (
            record.tenant.value,
            record.investigation_id.value if record.investigation_id is not None else None,
            record.actor,
            record.action,
            record.detail,
            record.occurred_at,
        )
        async with self._connection().cursor() as cursor:
            await cursor.execute(
                f"INSERT INTO audit ({_AUDIT_COLS}) VALUES ({_placeholders(6)})",
                params,
            )

    async def list_for_investigation(
        self, tenant: TenantId, investigation_id: InvestigationId
    ) -> tuple[AuditRecord, ...]:
        async with self._connection().cursor() as cursor:
            await cursor.execute(
                f"SELECT {_AUDIT_COLS} FROM audit "
                "WHERE tenant_id = %s AND investigation_id = %s ORDER BY id",
                (tenant.value, investigation_id.value),
            )
            rows = await cursor.fetchall()
        return tuple(_audit(row) for row in rows)


class PostgresUnitOfWork:
    """A unit of work over one psycopg connection with a manual transaction."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn: _Connection | None = None
        self.investigations: InvestigationRepository = _InvestigationRepository(self._require)
        self.jobs: JobQueue = _JobQueue(self._require)
        self.attempts: AttemptRepository = _AttemptRepository(self._require)
        self.evidence: EvidenceRepository = _EvidenceRepository(self._require)
        self.reports: ReportRepository = _ReportRepository(self._require)
        self.audit: AuditLog = _AuditLog(self._require)

    def _require(self) -> _Connection:
        if self._conn is None:
            raise RuntimeError("unit of work is not active")
        return self._conn

    async def commit(self) -> None:
        await self._require().commit()

    async def rollback(self) -> None:
        await self._require().rollback()

    async def __aenter__(self) -> "PostgresUnitOfWork":
        self._conn = await psycopg.AsyncConnection.connect(self._dsn, autocommit=False)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        connection = self._conn
        if connection is None:
            return
        try:
            if exc_type is not None:
                await connection.rollback()
        finally:
            await connection.close()
            self._conn = None


class PostgresUnitOfWorkFactory:
    """Creates units of work that each open their own connection to ``dsn``."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def __call__(self) -> UnitOfWork:
        return PostgresUnitOfWork(self._dsn)
