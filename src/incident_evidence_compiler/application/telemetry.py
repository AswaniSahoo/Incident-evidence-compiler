"""Telemetry source port and an in-memory fake.

The worker needs the metric signals to analyze for a given tenant/incident/run, but the
Phase 4 schema stores none. This port abstracts that source: Phase 6 ships an in-memory
fake for hermetic tests; a durable, RCAEval-backed source arrives in Phase 7 without
touching the worker.
"""

from collections.abc import Sequence
from typing import Protocol

from ..domain.baseline import SignalBaselineInput
from ..domain.identifiers import IncidentId, RunId, TenantId
from .errors import TelemetryUnavailableError

_Key = tuple[str, str, str]


class TelemetrySource(Protocol):
    async def load(
        self, tenant: TenantId, incident: IncidentId, run: RunId
    ) -> tuple[SignalBaselineInput, ...]:
        """Return the baseline inputs for the run, or raise ``TelemetryUnavailableError``."""
        ...


class InMemoryTelemetrySource:
    """A deterministic in-memory telemetry source for tests."""

    def __init__(self) -> None:
        self._signals: dict[_Key, tuple[SignalBaselineInput, ...]] = {}

    def set(
        self,
        tenant: TenantId,
        incident: IncidentId,
        run: RunId,
        signals: Sequence[SignalBaselineInput],
    ) -> None:
        self._signals[(tenant.value, incident.value, run.value)] = tuple(signals)

    async def load(
        self, tenant: TenantId, incident: IncidentId, run: RunId
    ) -> tuple[SignalBaselineInput, ...]:
        try:
            return self._signals[(tenant.value, incident.value, run.value)]
        except KeyError:
            raise TelemetryUnavailableError from None
