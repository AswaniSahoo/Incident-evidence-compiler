"""Durable persistence boundary.

Framework-independent contracts (records, status enums, typed errors, and repository /
unit-of-work protocols) plus in-memory fakes. This package may import ``domain``; the
domain must never import this package. Only the ``postgres`` submodule (added in a later
slice) imports a driver, and nothing opens a connection at import time.
"""

from .errors import (
    IdempotencyConflictError,
    InvalidPersistenceIdentifierError,
    InvalidPersistenceRecordError,
    InvalidPersistenceTimestampError,
    PersistenceError,
    PersistenceValidationError,
    RecordNotFoundError,
)
from .memory import InMemoryUnitOfWork, InMemoryUnitOfWorkFactory
from .records import (
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
from .repositories import (
    AttemptRepository,
    AuditLog,
    EvidenceRepository,
    InvestigationRepository,
    JobQueue,
    ReportRepository,
    UnitOfWork,
    UnitOfWorkFactory,
)

__all__ = [
    "AttemptId",
    "AttemptOutcome",
    "AttemptRecord",
    "AttemptRepository",
    "AuditLog",
    "AuditRecord",
    "ClaimedJob",
    "EvidenceRecord",
    "EvidenceRepository",
    "IdempotencyConflictError",
    "InMemoryUnitOfWork",
    "InMemoryUnitOfWorkFactory",
    "InvalidPersistenceIdentifierError",
    "InvalidPersistenceRecordError",
    "InvalidPersistenceTimestampError",
    "InvestigationId",
    "InvestigationRecord",
    "InvestigationRepository",
    "InvestigationStatus",
    "JobId",
    "JobQueue",
    "JobRecord",
    "JobStatus",
    "LedgerKind",
    "PersistenceError",
    "PersistenceValidationError",
    "RecordNotFoundError",
    "ReportRecord",
    "ReportRepository",
    "UnitOfWork",
    "UnitOfWorkFactory",
]
