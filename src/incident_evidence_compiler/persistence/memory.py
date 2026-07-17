"""In-memory fakes implementing the persistence protocols.

Framework-independent and standard-library only, these back the hermetic test gate.
Each unit of work operates on a copy-on-write snapshot of a shared store under an
``asyncio.Lock``; ``commit`` publishes the snapshot and leaving the scope without
committing discards it, giving transaction-like isolation without a database.

The true ``SELECT ... FOR UPDATE SKIP LOCKED`` claim race cannot be reproduced with
fidelity in memory; that behavior is exercised by the opt-in integration tests against
a real PostgreSQL, not here.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from uuid import UUID

from ..domain.identifiers import TenantId
from .errors import IdempotencyConflictError, InvalidPersistenceRecordError, RecordNotFoundError
from .records import (
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
    ReportRecord,
)
from .repositories import (
    AttemptRepository,
    AuditLog,
    EvidenceRepository,
    InvestigationRepository,
    JobQueue,
    ReportRepository,
    UnitOfWork,
)

_EvidenceKey = tuple[str, str, str]


class _Store:
    """The mutable in-memory tables shared across units of work."""

    def __init__(self) -> None:
        self.investigations: dict[UUID, InvestigationRecord] = {}
        self.jobs: dict[UUID, JobRecord] = {}
        self.attempts: dict[UUID, AttemptRecord] = {}
        self.evidence: dict[_EvidenceKey, EvidenceRecord] = {}
        self.reports: dict[UUID, ReportRecord] = {}
        self.audit: list[AuditRecord] = []

    def snapshot(self) -> "_Store":
        clone = _Store()
        clone.investigations = dict(self.investigations)
        clone.jobs = dict(self.jobs)
        clone.attempts = dict(self.attempts)
        clone.evidence = dict(self.evidence)
        clone.reports = dict(self.reports)
        clone.audit = list(self.audit)
        return clone

    def adopt(self, other: "_Store") -> None:
        self.investigations = other.investigations
        self.jobs = other.jobs
        self.attempts = other.attempts
        self.evidence = other.evidence
        self.reports = other.reports
        self.audit = other.audit


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)


class _InvestigationRepository:
    def __init__(self, store: _Store) -> None:
        self._store = store

    async def create(self, record: InvestigationRecord) -> InvestigationRecord:
        existing = self._by_key(record.tenant, record.idempotency_key)
        if existing is not None:
            return existing
        if record.investigation_id.value in self._store.investigations:
            raise IdempotencyConflictError
        self._store.investigations[record.investigation_id.value] = record
        return record

    def _by_key(self, tenant: TenantId, key: str | None) -> InvestigationRecord | None:
        if key is None:
            return None
        for record in self._store.investigations.values():
            if record.tenant == tenant and record.idempotency_key == key:
                return record
        return None

    async def get(self, tenant: TenantId, investigation_id: InvestigationId) -> InvestigationRecord:
        record = self._store.investigations.get(investigation_id.value)
        if record is None or record.tenant != tenant:
            raise RecordNotFoundError
        return record

    async def set_status(
        self, tenant: TenantId, investigation_id: InvestigationId, status: InvestigationStatus
    ) -> InvestigationRecord:
        record = await self.get(tenant, investigation_id)
        updated = replace(record, status=status, updated_at=datetime.now(UTC))
        self._store.investigations[investigation_id.value] = updated
        return updated


class _JobQueue:
    def __init__(self, store: _Store) -> None:
        self._store = store

    async def enqueue(self, record: JobRecord) -> JobRecord:
        if record.job_id.value in self._store.jobs:
            raise IdempotencyConflictError
        self._store.jobs[record.job_id.value] = record
        return record

    async def claim(
        self, worker_id: str, *, lease: timedelta, now: datetime | None = None
    ) -> ClaimedJob | None:
        if not worker_id.strip():
            raise InvalidPersistenceRecordError
        moment = _now(now)
        eligible = [job for job in self._store.jobs.values() if self._claimable(job, moment)]
        if not eligible:
            return None
        eligible.sort(key=lambda job: (job.available_at, str(job.job_id.value)))
        job = eligible[0]
        lease_expiry = moment + lease
        attempt_count = job.attempt_count + 1
        self._store.jobs[job.job_id.value] = replace(
            job,
            status=JobStatus.CLAIMED,
            claimed_by=worker_id,
            claimed_at=moment,
            lease_expires_at=lease_expiry,
            attempt_count=attempt_count,
            updated_at=moment,
        )
        return ClaimedJob(
            job_id=job.job_id,
            investigation_id=job.investigation_id,
            tenant=job.tenant,
            worker_id=worker_id,
            lease_expires_at=lease_expiry,
            attempt_count=attempt_count,
        )

    @staticmethod
    def _claimable(job: JobRecord, moment: datetime) -> bool:
        if job.status == JobStatus.QUEUED and job.available_at <= moment:
            return True
        return (
            job.status == JobStatus.CLAIMED
            and job.lease_expires_at is not None
            and job.lease_expires_at <= moment
        )

    async def get(self, tenant: TenantId, job_id: JobId) -> JobRecord:
        record = self._store.jobs.get(job_id.value)
        if record is None or record.tenant != tenant:
            raise RecordNotFoundError
        return record

    async def set_status(self, tenant: TenantId, job_id: JobId, status: JobStatus) -> JobRecord:
        record = await self.get(tenant, job_id)
        updated = replace(record, status=status, updated_at=datetime.now(UTC))
        self._store.jobs[job_id.value] = updated
        return updated


class _AttemptRepository:
    def __init__(self, store: _Store) -> None:
        self._store = store

    async def record(self, record: AttemptRecord) -> AttemptRecord:
        for existing in self._store.attempts.values():
            duplicate = (
                existing.job_id == record.job_id
                and existing.attempt_number == record.attempt_number
            )
            if duplicate:
                raise IdempotencyConflictError
        self._store.attempts[record.attempt_id.value] = record
        return record

    async def list_for_job(self, tenant: TenantId, job_id: JobId) -> tuple[AttemptRecord, ...]:
        items = [
            attempt
            for attempt in self._store.attempts.values()
            if attempt.tenant == tenant and attempt.job_id == job_id
        ]
        items.sort(key=lambda attempt: attempt.attempt_number)
        return tuple(items)


class _EvidenceRepository:
    def __init__(self, store: _Store) -> None:
        self._store = store

    async def append(self, records: Sequence[EvidenceRecord]) -> tuple[EvidenceRecord, ...]:
        stored: list[EvidenceRecord] = []
        for record in records:
            key = (record.tenant.value, record.run.value, record.evidence_id.value)
            existing = self._store.evidence.get(key)
            if existing is not None:
                stored.append(existing)
                continue
            self._store.evidence[key] = record
            stored.append(record)
        return tuple(stored)

    async def list_for_investigation(
        self, tenant: TenantId, investigation_id: InvestigationId
    ) -> tuple[EvidenceRecord, ...]:
        items = [
            record
            for record in self._store.evidence.values()
            if record.tenant == tenant and record.investigation_id == investigation_id
        ]
        items.sort(key=lambda record: record.evidence_id.value)
        return tuple(items)


class _ReportRepository:
    def __init__(self, store: _Store) -> None:
        self._store = store

    async def put(self, record: ReportRecord) -> ReportRecord:
        if record.investigation_id.value in self._store.reports:
            raise IdempotencyConflictError
        self._store.reports[record.investigation_id.value] = record
        return record

    async def get(self, tenant: TenantId, investigation_id: InvestigationId) -> ReportRecord:
        record = self._store.reports.get(investigation_id.value)
        if record is None or record.tenant != tenant:
            raise RecordNotFoundError
        return record


class _AuditLog:
    def __init__(self, store: _Store) -> None:
        self._store = store

    async def record(self, record: AuditRecord) -> None:
        self._store.audit.append(record)

    async def list_for_investigation(
        self, tenant: TenantId, investigation_id: InvestigationId
    ) -> tuple[AuditRecord, ...]:
        return tuple(
            record
            for record in self._store.audit
            if record.tenant == tenant and record.investigation_id == investigation_id
        )


class InMemoryUnitOfWork:
    """A copy-on-write unit of work over a shared in-memory store."""

    def __init__(self, shared: _Store, lock: asyncio.Lock) -> None:
        self._shared = shared
        self._lock = lock
        self._working = shared.snapshot()
        self.investigations: InvestigationRepository = _InvestigationRepository(self._working)
        self.jobs: JobQueue = _JobQueue(self._working)
        self.attempts: AttemptRepository = _AttemptRepository(self._working)
        self.evidence: EvidenceRepository = _EvidenceRepository(self._working)
        self.reports: ReportRepository = _ReportRepository(self._working)
        self.audit: AuditLog = _AuditLog(self._working)

    def _rebind(self) -> None:
        self.investigations = _InvestigationRepository(self._working)
        self.jobs = _JobQueue(self._working)
        self.attempts = _AttemptRepository(self._working)
        self.evidence = _EvidenceRepository(self._working)
        self.reports = _ReportRepository(self._working)
        self.audit = _AuditLog(self._working)

    async def commit(self) -> None:
        self._shared.adopt(self._working)
        self._working = self._shared.snapshot()
        self._rebind()

    async def rollback(self) -> None:
        self._working = self._shared.snapshot()
        self._rebind()

    async def __aenter__(self) -> "InMemoryUnitOfWork":
        await self._lock.acquire()
        try:
            self._working = self._shared.snapshot()
            self._rebind()
        except BaseException:
            self._lock.release()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._lock.release()


class InMemoryUnitOfWorkFactory:
    """Creates units of work sharing one in-memory store (a fake database)."""

    def __init__(self) -> None:
        self._store = _Store()
        self._lock = asyncio.Lock()

    def __call__(self) -> UnitOfWork:
        return InMemoryUnitOfWork(self._store, self._lock)
