"""Typed persistence records, surrogate identifiers, and status enums.

Framework-independent: this module depends only on the standard library and the
domain contracts. It never imports a driver and opens no connections. Records are
frozen and slotted, matching the domain style, and validate their invariants so no
anonymous dictionaries cross the persistence boundary.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from ..domain.identifiers import EvidenceId, IncidentId, RunId, TenantId
from ..domain.incidents import IncidentWindow
from .errors import (
    InvalidPersistenceIdentifierError,
    InvalidPersistenceRecordError,
    InvalidPersistenceTimestampError,
)


def _check_uuid(value: object) -> None:
    if not isinstance(value, UUID):
        raise InvalidPersistenceIdentifierError


def _check_aware(value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InvalidPersistenceTimestampError


def _check_optional_aware(value: object) -> None:
    if value is not None:
        _check_aware(value)


def _check_text(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidPersistenceRecordError


def _check_optional_text(value: object) -> None:
    if value is not None:
        _check_text(value)


def _check_count(value: object, *, minimum: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise InvalidPersistenceRecordError


@dataclass(frozen=True, slots=True)
class InvestigationId:
    """Surrogate primary key for an investigation."""

    value: UUID

    def __post_init__(self) -> None:
        _check_uuid(self.value)


@dataclass(frozen=True, slots=True)
class JobId:
    """Surrogate primary key for a queued job."""

    value: UUID

    def __post_init__(self) -> None:
        _check_uuid(self.value)


@dataclass(frozen=True, slots=True)
class AttemptId:
    """Surrogate primary key for a job execution attempt."""

    value: UUID

    def __post_init__(self) -> None:
        _check_uuid(self.value)


class InvestigationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStatus(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class LedgerKind(StrEnum):
    METRIC = "metric"
    CHANGE = "change"


@dataclass(frozen=True, slots=True)
class InvestigationRecord:
    """A durable investigation request row."""

    investigation_id: InvestigationId
    tenant: TenantId
    incident: IncidentId
    run: RunId
    window: IncidentWindow
    status: InvestigationStatus
    idempotency_key: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _check_optional_text(self.idempotency_key)
        _check_aware(self.created_at)
        _check_aware(self.updated_at)


@dataclass(frozen=True, slots=True)
class JobRecord:
    """A claimable queue row for one investigation stage."""

    job_id: JobId
    investigation_id: InvestigationId
    tenant: TenantId
    status: JobStatus
    available_at: datetime
    claimed_by: str | None
    claimed_at: datetime | None
    lease_expires_at: datetime | None
    attempt_count: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _check_aware(self.available_at)
        _check_optional_text(self.claimed_by)
        _check_optional_aware(self.claimed_at)
        _check_optional_aware(self.lease_expires_at)
        _check_count(self.attempt_count, minimum=0)
        _check_count(self.max_attempts, minimum=1)
        _check_aware(self.created_at)
        _check_aware(self.updated_at)


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    """The subset of a job returned to the worker that claimed it."""

    job_id: JobId
    investigation_id: InvestigationId
    tenant: TenantId
    worker_id: str
    lease_expires_at: datetime
    attempt_count: int

    def __post_init__(self) -> None:
        _check_text(self.worker_id)
        _check_aware(self.lease_expires_at)
        _check_count(self.attempt_count, minimum=1)


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """An append-only record of one job execution attempt."""

    attempt_id: AttemptId
    job_id: JobId
    tenant: TenantId
    attempt_number: int
    worker_id: str
    started_at: datetime
    finished_at: datetime | None
    outcome: AttemptOutcome | None
    error_code: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        _check_count(self.attempt_number, minimum=1)
        _check_text(self.worker_id)
        _check_aware(self.started_at)
        _check_optional_aware(self.finished_at)
        _check_optional_text(self.error_code)
        _check_aware(self.created_at)


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """A content-addressed persisted evidence-ledger entry."""

    tenant: TenantId
    investigation_id: InvestigationId
    run: RunId
    evidence_id: EvidenceId
    ledger_kind: LedgerKind
    schema_version: str
    payload: str
    created_at: datetime

    def __post_init__(self) -> None:
        _check_text(self.schema_version)
        _check_text(self.payload)
        _check_aware(self.created_at)


@dataclass(frozen=True, slots=True)
class ReportRecord:
    """The replayable incident report for one investigation."""

    investigation_id: InvestigationId
    tenant: TenantId
    run: RunId
    schema_version: str
    payload: str
    created_at: datetime

    def __post_init__(self) -> None:
        _check_text(self.schema_version)
        _check_text(self.payload)
        _check_aware(self.created_at)


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """An append-only, sanitized audit event."""

    tenant: TenantId
    investigation_id: InvestigationId | None
    actor: str
    action: str
    detail: str | None
    occurred_at: datetime

    def __post_init__(self) -> None:
        _check_text(self.actor)
        _check_text(self.action)
        _check_optional_text(self.detail)
        _check_aware(self.occurred_at)
