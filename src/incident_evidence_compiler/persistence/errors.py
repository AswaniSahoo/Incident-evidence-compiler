"""Typed, sanitized persistence-boundary failures.

These mirror the domain error convention: a stable ``code`` class variable and no
free-form message, so a failure crossing the boundary never leaks tenant data, keys,
payloads, or driver internals.
"""

from typing import ClassVar


class PersistenceError(Exception):
    """Base class for stable persistence-boundary errors."""

    code: ClassVar[str] = "persistence_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class PersistenceValidationError(PersistenceError, ValueError):
    """Base class for invalid persistence input."""


class InvalidPersistenceIdentifierError(PersistenceValidationError):
    code = "invalid_persistence_identifier"


class InvalidPersistenceTimestampError(PersistenceValidationError):
    code = "invalid_persistence_timestamp"


class InvalidPersistenceRecordError(PersistenceValidationError):
    code = "invalid_persistence_record"


class IdempotencyConflictError(PersistenceError):
    """A unique/idempotency constraint would be violated by conflicting content."""

    code = "idempotency_conflict"


class RecordNotFoundError(PersistenceError):
    """A tenant-scoped lookup found no matching row."""

    code = "record_not_found"
