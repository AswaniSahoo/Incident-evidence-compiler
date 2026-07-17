"""Framework-independent application use-cases.

Each use-case orchestrates the ports (persistence unit of work) and returns typed records.
They are pure of any web framework and are exercised directly against the in-memory fakes.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..domain.identifiers import TenantId
from ..persistence import (
    AuditRecord,
    InvestigationId,
    InvestigationRecord,
    InvestigationStatus,
    JobId,
    JobRecord,
    JobStatus,
    RecordNotFoundError,
    ReportRecord,
    UnitOfWorkFactory,
)
from .contracts import CreateInvestigationCommand
from .errors import InvestigationNotFoundError, ReportNotReadyError

DEFAULT_MAX_ATTEMPTS = 3


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CreateInvestigation:
    """Open an investigation and enqueue its work, idempotently."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = _utcnow,
        id_factory: Callable[[], UUID] = uuid4,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._id_factory = id_factory
        self._max_attempts = max_attempts

    async def execute(self, command: CreateInvestigationCommand) -> InvestigationId:
        now = self._clock()
        investigation_id = InvestigationId(self._id_factory())
        async with self._uow_factory() as uow:
            stored = await uow.investigations.create(
                InvestigationRecord(
                    investigation_id=investigation_id,
                    tenant=command.tenant,
                    incident=command.incident,
                    run=command.run,
                    window=command.window,
                    status=InvestigationStatus.PENDING,
                    idempotency_key=command.idempotency_key,
                    created_at=now,
                    updated_at=now,
                )
            )
            # Only enqueue work for a genuinely new investigation; an idempotent replay
            # returns the existing record and must not create a duplicate job.
            if stored.investigation_id == investigation_id:
                await uow.jobs.enqueue(
                    JobRecord(
                        job_id=JobId(self._id_factory()),
                        investigation_id=investigation_id,
                        tenant=command.tenant,
                        status=JobStatus.QUEUED,
                        available_at=now,
                        claimed_by=None,
                        claimed_at=None,
                        lease_expires_at=None,
                        attempt_count=0,
                        max_attempts=self._max_attempts,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await uow.audit.record(
                    AuditRecord(
                        tenant=command.tenant,
                        investigation_id=investigation_id,
                        actor="control-plane",
                        action="investigation.created",
                        detail=None,
                        occurred_at=now,
                    )
                )
            await uow.commit()
        return stored.investigation_id


class GetInvestigationStatus:
    """Return a tenant's investigation record or raise ``InvestigationNotFoundError``."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(
        self, tenant: TenantId, investigation_id: InvestigationId
    ) -> InvestigationRecord:
        async with self._uow_factory() as uow:
            try:
                return await uow.investigations.get(tenant, investigation_id)
            except RecordNotFoundError:
                raise InvestigationNotFoundError from None


class GetReport:
    """Return a tenant's report, or a typed not-found/not-ready error."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, tenant: TenantId, investigation_id: InvestigationId) -> ReportRecord:
        async with self._uow_factory() as uow:
            try:
                await uow.investigations.get(tenant, investigation_id)
            except RecordNotFoundError:
                raise InvestigationNotFoundError from None
            try:
                return await uow.reports.get(tenant, investigation_id)
            except RecordNotFoundError:
                raise ReportNotReadyError from None
