"""Typed, sanitized domain failures."""

from typing import ClassVar


class DomainError(Exception):
    """Base class for stable domain errors."""

    code: ClassVar[str] = "domain_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class DomainValidationError(DomainError, ValueError):
    """Base class for invalid domain input."""


class InvalidIdentifierError(DomainValidationError):
    code = "invalid_identifier"


class InvalidTimestampError(DomainValidationError):
    code = "invalid_timestamp"


class InvalidIncidentWindowError(DomainValidationError):
    code = "invalid_incident_window"


class InvalidMetricPointError(DomainValidationError):
    code = "invalid_metric_point"


class InvalidMetricSignalError(DomainValidationError):
    code = "invalid_metric_signal"


class InvalidBaselineConfigurationError(DomainValidationError):
    code = "invalid_baseline_configuration"


class DuplicateSignalError(DomainValidationError):
    code = "duplicate_signal"


class BaselineComputationError(DomainError, ArithmeticError):
    code = "baseline_computation_failed"


class InvalidEvidenceLedgerError(DomainValidationError):
    code = "invalid_evidence_ledger"


class InvalidHypothesisError(DomainValidationError):
    code = "invalid_hypothesis"


class CanonicalSerializationError(DomainValidationError):
    code = "canonical_serialization_failed"
