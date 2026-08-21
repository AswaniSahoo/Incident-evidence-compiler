"""A labelled RCAEval-backed demo telemetry source (ADR 0016).

This is a *demo* source, not production telemetry ingestion. It reuses the existing bounded,
audited RCAEval primitives to index an already-extracted split (outside the repo, ADR 0009)
by each case's directory path, and resolves an investigation's ``incident_id`` to that case's
metric signals. It reads only the metric CSV, the injection time, and the directory path — it
never consults the evaluation sidecar or any ground-truth label, and performs no scoring.
"""

from pathlib import Path

from ..application import TelemetryUnavailableError
from ..domain.baseline import SignalBaselineInput
from ..domain.identifiers import IncidentId, RunId, TenantId
from ..domain.incidents import IncidentWindow
from ..evaluation.harness.baseline_inputs import ScaleFloorPolicy, to_baseline_inputs
from ..evaluation.rcaeval.csv_loader import parse_case
from ..evaluation.rcaeval.discovery import discover_cases, validate_root
from ..evaluation.rcaeval.errors import RcaevalLoadError
from ..evaluation.rcaeval.ids import parse_split, random_case_id
from ..evaluation.rcaeval.limits import LoaderLimits


class RcaevalTelemetrySource:
    """Resolve an ``incident_id`` (a case directory path) to that case's baseline inputs."""

    def __init__(
        self,
        root: Path,
        *,
        split: str = "OB",
        limits: LoaderLimits | None = None,
        floor_policy: ScaleFloorPolicy | None = None,
    ) -> None:
        parsed_split = parse_split(split)
        validate_root(root, parsed_split)
        bounded_limits = limits if limits is not None else LoaderLimits()
        floors = floor_policy if floor_policy is not None else ScaleFloorPolicy()
        self._inputs: dict[str, tuple[SignalBaselineInput, ...]] = {}
        self._windows: dict[str, IncidentWindow] = {}
        for source in discover_cases(root, bounded_limits):
            try:
                # ``case_id`` is provenance metadata for the parser only; it never leaves here.
                parsed = parse_case(source, random_case_id(), bounded_limits)
            except RcaevalLoadError:
                # Skip a case the strict per-case parser rejects (for example the documented
                # trailing-empty-timestamp rows in RE2-OB, ADR 0010); the server still serves
                # every parseable case.
                continue
            key = source.source_locator
            self._inputs[key] = to_baseline_inputs(parsed.signals, floor_policy=floors)
            self._windows[key] = parsed.window

    @property
    def available(self) -> dict[str, IncidentWindow]:
        """A read-only copy of ``{incident_id: incident_window}`` for every parseable case."""
        return dict(self._windows)

    async def load(
        self, tenant: TenantId, incident: IncidentId, run: RunId, window: IncidentWindow
    ) -> tuple[SignalBaselineInput, ...]:
        # ``window`` is unused: each case's signals are pre-indexed from its own CSV, and the
        # case's authoritative window is already exposed via ``available``.
        try:
            return self._inputs[incident.value]
        except KeyError:
            raise TelemetryUnavailableError from None
