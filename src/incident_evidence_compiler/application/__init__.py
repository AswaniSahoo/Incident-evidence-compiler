"""Framework-independent application core.

Use-cases (create investigation, get status, get report) and the investigation ``Worker``,
wired to the persistence and LLM ports plus a ``TelemetrySource``. Nothing here imports a
web framework or a driver; the control-plane adapter (Phase 6b) calls these.
"""

from .contracts import CreateInvestigationCommand
from .errors import (
    ApplicationError,
    InvestigationNotFoundError,
    ReportNotReadyError,
    TelemetryUnavailableError,
)
from .telemetry import InMemoryTelemetrySource, TelemetrySource
from .use_cases import CreateInvestigation, GetInvestigationStatus, GetReport
from .worker import DEFAULT_BASELINE_POLICY, Worker

__all__ = [
    "DEFAULT_BASELINE_POLICY",
    "ApplicationError",
    "CreateInvestigation",
    "CreateInvestigationCommand",
    "GetInvestigationStatus",
    "GetReport",
    "InMemoryTelemetrySource",
    "InvestigationNotFoundError",
    "ReportNotReadyError",
    "TelemetrySource",
    "TelemetryUnavailableError",
    "Worker",
]
