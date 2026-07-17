"""Repository and unit-of-work protocols for the persistence boundary.

These are structural ``typing.Protocol``s: the in-memory fakes and the future async
``psycopg`` driver both satisfy them, so callers (the worker and control plane in
later phases) depend on these contracts rather than on any concrete backend. Every
method is asynchronous and every query is tenant-scoped.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from types import TracebackType
from typing import Protocol

from ..domain.identifiers import TenantId
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


class InvestigationRepository(Protocol):
    async def create(self, record: InvestigationRecord) -> InvestigationRecord:
        """Persist an investigation.

        Idempotent on ``(tenant, idempotency_key)``: replaying a create with an
        already-seen key returns the existing record instead of inserting a duplicate.
        """
        ...

    async def get(self, tenant: TenantId, investigation_id: InvestigationId) -> InvestigationRecord:
        """Return the tenant's investigation or raise ``RecordNotFoundError``."""
        ...

    async def set_status(
        self, tenant: TenantId, investigation_id: InvestigationId, status: InvestigationStatus
    ) -> InvestigationRecord: ...


class JobQueue(Protocol):
    async def enqueue(self, record: JobRecord) -> JobRecord: ...

    async def claim(
        self, worker_id: str, *, lease: timedelta, now: datetime | None = None
    ) -> ClaimedJob | None:
        """Atomically claim the oldest eligible job, or return ``None`` if none.

        A job is eligible when it is queued and due, or when a prior claim's lease has
        expired. The concrete driver realizes this with ``SELECT ... FOR UPDATE SKIP
        LOCKED`` so concurrent workers never claim the same job twice.
        """
        ...

    async def get(self, tenant: TenantId, job_id: JobId) -> JobRecord: ...

    async def set_status(self, tenant: TenantId, job_id: JobId, status: JobStatus) -> JobRecord: ...


class AttemptRepository(Protocol):
    async def record(self, record: AttemptRecord) -> AttemptRecord:
        """Append an attempt; unique on ``(job_id, attempt_number)``."""
        ...

    async def list_for_job(self, tenant: TenantId, job_id: JobId) -> tuple[AttemptRecord, ...]: ...


class EvidenceRepository(Protocol):
    async def append(self, records: Sequence[EvidenceRecord]) -> tuple[EvidenceRecord, ...]:
        """Append evidence idempotently by ``(tenant, run, evidence_id)``.

        Content-addressed entries are deduplicated: an already-stored evidence id is
        returned unchanged rather than duplicated.
        """
        ...

    async def list_for_investigation(
        self, tenant: TenantId, investigation_id: InvestigationId
    ) -> tuple[EvidenceRecord, ...]: ...


class ReportRepository(Protocol):
    async def put(self, record: ReportRecord) -> ReportRecord:
        """Store the single report for an investigation.

        Raises ``IdempotencyConflictError`` if a report already exists for it.
        """
        ...

    async def get(self, tenant: TenantId, investigation_id: InvestigationId) -> ReportRecord: ...


class AuditLog(Protocol):
    async def record(self, record: AuditRecord) -> None: ...

    async def list_for_investigation(
        self, tenant: TenantId, investigation_id: InvestigationId
    ) -> tuple[AuditRecord, ...]: ...


class UnitOfWork(Protocol):
    """A transactional scope exposing the repositories.

    Enter the context, perform work through the repositories, then ``commit``. Leaving
    the context without committing (including on exception) discards the work.
    """

    investigations: InvestigationRepository
    jobs: JobQueue
    attempts: AttemptRepository
    evidence: EvidenceRepository
    reports: ReportRepository
    audit: AuditLog

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def __aenter__(self) -> "UnitOfWork": ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...
