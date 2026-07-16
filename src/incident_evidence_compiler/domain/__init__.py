"""Public, framework-independent domain contracts."""

from .baseline import (
    AbstentionReason,
    BaselineAbstention,
    BaselinePolicy,
    BaselineRanking,
    BaselineResult,
    SignalBaselineInput,
    SignalEvaluation,
    SuspicionCandidate,
    rank_metric_shifts,
)
from .errors import (
    BaselineComputationError,
    DomainError,
    DomainValidationError,
    DuplicateSignalError,
    InvalidBaselineConfigurationError,
    InvalidIdentifierError,
    InvalidIncidentWindowError,
    InvalidMetricPointError,
    InvalidMetricSignalError,
    InvalidTimestampError,
)
from .identifiers import CaseId, EvidenceId, IncidentId, RunId, TenantId
from .incidents import IncidentWindow
from .metrics import MetricPoint, MetricSignal, SignalKey

__all__ = [
    "AbstentionReason",
    "BaselineAbstention",
    "BaselineComputationError",
    "BaselinePolicy",
    "BaselineRanking",
    "BaselineResult",
    "CaseId",
    "DomainError",
    "DomainValidationError",
    "DuplicateSignalError",
    "EvidenceId",
    "IncidentId",
    "IncidentWindow",
    "InvalidBaselineConfigurationError",
    "InvalidIdentifierError",
    "InvalidIncidentWindowError",
    "InvalidMetricPointError",
    "InvalidMetricSignalError",
    "InvalidTimestampError",
    "MetricPoint",
    "MetricSignal",
    "RunId",
    "SignalBaselineInput",
    "SignalEvaluation",
    "SignalKey",
    "SuspicionCandidate",
    "TenantId",
    "rank_metric_shifts",
]
