"""Canonical metric signal contracts."""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from .errors import InvalidIdentifierError, InvalidMetricPointError, InvalidMetricSignalError
from .incidents import to_utc


@dataclass(frozen=True, slots=True, order=True)
class SignalKey:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise InvalidIdentifierError


@dataclass(frozen=True, slots=True)
class MetricPoint:
    observed_at: datetime
    value: float

    def __post_init__(self) -> None:
        observed_at = to_utc(self.observed_at)
        if isinstance(self.value, bool):
            raise InvalidMetricPointError
        try:
            value = float(self.value)
        except (OverflowError, TypeError, ValueError):
            pass
        else:
            if math.isfinite(value):
                object.__setattr__(self, "observed_at", observed_at)
                object.__setattr__(self, "value", value)
                return
        raise InvalidMetricPointError from None


@dataclass(frozen=True, slots=True, init=False)
class MetricSignal:
    key: SignalKey
    points: tuple[MetricPoint, ...]

    def __init__(self, key: SignalKey, points: Iterable[MetricPoint]) -> None:
        if not isinstance(key, SignalKey):
            raise InvalidMetricSignalError
        materialized = tuple(points)
        if not all(isinstance(point, MetricPoint) for point in materialized):
            raise InvalidMetricSignalError
        if any(
            current.observed_at >= following.observed_at
            for current, following in pairwise(materialized)
        ):
            raise InvalidMetricSignalError
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "points", materialized)
