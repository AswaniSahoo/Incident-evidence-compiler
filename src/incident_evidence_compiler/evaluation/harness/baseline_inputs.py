"""Bridge adapter-loaded telemetry into deterministic-baseline inputs.

An ``InvestigationCase`` carries the metric signals present in a case's telemetry
columns but no per-signal scale floor, which the baseline requires to be strictly
positive. This module derives that floor from each signal's own magnitude and
maps a signal key to its owning service using only the telemetry column name
(never a ground-truth label).
"""

from collections.abc import Iterable
from statistics import median

from ...domain import BaselinePolicy, MetricSignal, SignalBaselineInput

# The smallest strictly-positive floor, used only to satisfy the baseline's
# ``absolute_scale_floor > 0`` invariant for near-zero-magnitude signals.
DEFAULT_ABSOLUTE_EPSILON = 1e-9

# Fraction of a signal's own median magnitude used as its absolute scale floor,
# so a near-constant signal needs a change proportional to its own level (not an
# arbitrary absolute amount) before it can score as suspicious. This is a
# development-set default, not a published calibration curve.
DEFAULT_RELATIVE_FLOOR_FRACTION = 0.05

# The baseline policy used by the evaluation harness. ``minimum_score`` is a
# robust-sigma threshold; the per-signal magnitude flooring is carried by each
# input's ``absolute_scale_floor`` (below), so the policy's own
# ``relative_scale_floor`` is left at zero to avoid double-counting.
DEFAULT_EVALUATION_POLICY = BaselinePolicy(
    minimum_points_per_window=2,
    minimum_score=3.0,
    minimum_margin=0.0,
    relative_scale_floor=0.0,
)


class ScaleFloorPolicy:
    """Derive a strictly-positive per-signal absolute scale floor.

    The floor is ``max(absolute_epsilon, relative_floor_fraction * median(|value|))``
    over a signal's observed values, so it scales with the signal's own magnitude
    and never collapses to zero.
    """

    __slots__ = ("absolute_epsilon", "relative_floor_fraction")

    def __init__(
        self,
        *,
        relative_floor_fraction: float = DEFAULT_RELATIVE_FLOOR_FRACTION,
        absolute_epsilon: float = DEFAULT_ABSOLUTE_EPSILON,
    ) -> None:
        if not (relative_floor_fraction >= 0.0):
            raise ValueError("relative_floor_fraction must be non-negative")
        if not (absolute_epsilon > 0.0):
            raise ValueError("absolute_epsilon must be strictly positive")
        self.relative_floor_fraction = float(relative_floor_fraction)
        self.absolute_epsilon = float(absolute_epsilon)

    def floor_for(self, signal: MetricSignal) -> float:
        magnitudes = [abs(point.value) for point in signal.points]
        if not magnitudes:
            return self.absolute_epsilon
        typical = float(median(magnitudes))
        return max(self.absolute_epsilon, self.relative_floor_fraction * typical)


def service_of(signal_key_value: str) -> str:
    """Map a telemetry column name to its owning service.

    RCAEval RE2 ``simple_metrics.csv`` columns are ``<service>_<metric>`` where the
    single underscore separates the service from the metric (services and metrics
    may themselves contain hyphens, e.g. ``frontend-external_workload`` and
    ``checkoutservice_latency-90``). The service is therefore everything before the
    final underscore. A column with no underscore is treated as its own service.
    """
    service, separator, _metric = signal_key_value.rpartition("_")
    return service if separator else signal_key_value


def to_baseline_inputs(
    signals: Iterable[MetricSignal],
    *,
    floor_policy: ScaleFloorPolicy | None = None,
) -> tuple[SignalBaselineInput, ...]:
    """Wrap each metric signal with a strictly-positive derived scale floor."""
    policy = floor_policy if floor_policy is not None else ScaleFloorPolicy()
    return tuple(
        SignalBaselineInput(signal=signal, absolute_scale_floor=policy.floor_for(signal))
        for signal in signals
    )
