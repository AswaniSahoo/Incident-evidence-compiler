"""Typed, sanitized application-boundary failures.

Stable ``code`` class variables and no free-form message, mirroring the domain,
persistence, and LLM error conventions, so a failure crossing the boundary never leaks
tenant data, model text, or internals. The control-plane adapter maps these to HTTP
status codes.
"""

from typing import ClassVar


class ApplicationError(Exception):
    """Base class for stable application-boundary errors."""

    code: ClassVar[str] = "application_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class InvestigationNotFoundError(ApplicationError):
    """No investigation matched the tenant-scoped lookup (maps to 404)."""

    code = "investigation_not_found"


class ReportNotReadyError(ApplicationError):
    """The investigation exists but has produced no report yet (maps to 409)."""

    code = "report_not_ready"


class TelemetryUnavailableError(ApplicationError):
    """No telemetry is available for the investigation's tenant/incident/run."""

    code = "telemetry_unavailable"
