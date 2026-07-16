"""Deterministic metric-shift suspicion baseline."""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from statistics import StatisticsError, median

from .errors import (
    BaselineComputationError,
    DuplicateSignalError,
    InvalidBaselineConfigurationError,
)
from .incidents import IncidentWindow
from .metrics import MetricSignal, SignalKey


def _finite_nonnegative(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidBaselineConfigurationError
    try:
        converted = float(value)
    except (OverflowError, TypeError, ValueError):
        pass
    else:
        if math.isfinite(converted) and converted >= 0.0:
            return converted
    raise InvalidBaselineConfigurationError from None


@dataclass(frozen=True, slots=True)
class BaselinePolicy:
    minimum_points_per_window: int
    minimum_score: float
    minimum_margin: float
    relative_scale_floor: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.minimum_points_per_window, bool)
            or not isinstance(self.minimum_points_per_window, int)
            or self.minimum_points_per_window < 1
        ):
            raise InvalidBaselineConfigurationError
        object.__setattr__(self, "minimum_score", _finite_nonnegative(self.minimum_score))
        object.__setattr__(self, "minimum_margin", _finite_nonnegative(self.minimum_margin))
        object.__setattr__(
            self,
            "relative_scale_floor",
            _finite_nonnegative(self.relative_scale_floor),
        )


@dataclass(frozen=True, slots=True)
class SignalBaselineInput:
    signal: MetricSignal
    absolute_scale_floor: float

    def __post_init__(self) -> None:
        if not isinstance(self.signal, MetricSignal):
            raise InvalidBaselineConfigurationError
        floor = _finite_nonnegative(self.absolute_scale_floor)
        if floor <= 0.0:
            raise InvalidBaselineConfigurationError
        object.__setattr__(self, "absolute_scale_floor", floor)


@dataclass(frozen=True, slots=True)
class SuspicionCandidate:
    signal_key: SignalKey
    pre_point_count: int
    post_point_count: int
    pre_median: float
    post_median: float
    pre_mad: float
    absolute_scale_floor: float
    relative_scale_floor: float
    scale: float
    signed_score: float
    suspicion_score: float


@dataclass(frozen=True, slots=True)
class SignalEvaluation:
    """Replay snapshot for one configured signal, whether or not it was eligible."""

    signal_key: SignalKey
    absolute_scale_floor: float
    pre_point_count: int
    post_point_count: int
    eligible: bool
    candidate: SuspicionCandidate | None


class AbstentionReason(StrEnum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    WEAK_EVIDENCE = "weak_evidence"
    AMBIGUOUS_EVIDENCE = "ambiguous_evidence"


@dataclass(frozen=True, slots=True)
class BaselineRanking:
    policy: BaselinePolicy
    signal_evaluations: tuple[SignalEvaluation, ...]
    candidates: tuple[SuspicionCandidate, ...]
    lead: float


@dataclass(frozen=True, slots=True)
class BaselineAbstention:
    policy: BaselinePolicy
    reason: AbstentionReason
    signal_evaluations: tuple[SignalEvaluation, ...]
    evaluated_candidates: tuple[SuspicionCandidate, ...]
    eligible_signal_count: int
    top_score: float | None
    second_score: float | None


type BaselineResult = BaselineRanking | BaselineAbstention


def _require_finite(*values: float) -> None:
    if not all(math.isfinite(value) for value in values):
        raise BaselineComputationError


def _score_candidate(
    item: SignalBaselineInput,
    policy: BaselinePolicy,
    pre_values: tuple[float, ...],
    post_values: tuple[float, ...],
) -> SuspicionCandidate:
    try:
        pre_center = float(median(pre_values))
        post_center = float(median(post_values))
        deviations = tuple(abs(value - pre_center) for value in pre_values)
        pre_mad = float(median(deviations))
        robust_scale = 1.4826 * pre_mad
        relative_scale = policy.relative_scale_floor * max(
            abs(pre_center), item.absolute_scale_floor
        )
        scale = max(robust_scale, item.absolute_scale_floor, relative_scale)
        signed_score = (post_center - pre_center) / scale
        suspicion_score = abs(signed_score)
    except (OverflowError, StatisticsError, ZeroDivisionError):
        pass
    else:
        _require_finite(
            pre_center,
            post_center,
            pre_mad,
            robust_scale,
            relative_scale,
            scale,
            signed_score,
            suspicion_score,
        )
        return SuspicionCandidate(
            signal_key=item.signal.key,
            pre_point_count=len(pre_values),
            post_point_count=len(post_values),
            pre_median=pre_center,
            post_median=post_center,
            pre_mad=pre_mad,
            absolute_scale_floor=item.absolute_scale_floor,
            relative_scale_floor=policy.relative_scale_floor,
            scale=scale,
            signed_score=signed_score,
            suspicion_score=suspicion_score,
        )
    raise BaselineComputationError from None


def _evaluate_signal(
    window: IncidentWindow,
    item: SignalBaselineInput,
    policy: BaselinePolicy,
) -> SignalEvaluation:
    pre_values = tuple(
        point.value
        for point in item.signal.points
        if window.start <= point.observed_at < window.injection
    )
    post_values = tuple(
        point.value
        for point in item.signal.points
        if window.injection <= point.observed_at < window.end
    )
    eligible = (
        len(pre_values) >= policy.minimum_points_per_window
        and len(post_values) >= policy.minimum_points_per_window
    )
    candidate = _score_candidate(item, policy, pre_values, post_values) if eligible else None
    return SignalEvaluation(
        signal_key=item.signal.key,
        absolute_scale_floor=item.absolute_scale_floor,
        pre_point_count=len(pre_values),
        post_point_count=len(post_values),
        eligible=eligible,
        candidate=candidate,
    )


def rank_metric_shifts(
    window: IncidentWindow,
    inputs: Iterable[SignalBaselineInput],
    policy: BaselinePolicy,
) -> BaselineResult:
    """Rank robust median shifts, or explicitly abstain."""
    materialized = tuple(inputs)
    if not all(isinstance(item, SignalBaselineInput) for item in materialized):
        raise InvalidBaselineConfigurationError
    keys = tuple(item.signal.key.value for item in materialized)
    if len(set(keys)) != len(keys):
        raise DuplicateSignalError
    signal_evaluations = tuple(
        sorted(
            (_evaluate_signal(window, item, policy) for item in materialized),
            key=lambda evaluation: evaluation.signal_key.value,
        )
    )
    candidates = tuple(
        sorted(
            (
                evaluation.candidate
                for evaluation in signal_evaluations
                if evaluation.candidate is not None
            ),
            key=lambda candidate: (-candidate.suspicion_score, candidate.signal_key.value),
        )
    )
    if not candidates:
        return BaselineAbstention(
            policy=policy,
            reason=AbstentionReason.INSUFFICIENT_EVIDENCE,
            signal_evaluations=signal_evaluations,
            evaluated_candidates=(),
            eligible_signal_count=0,
            top_score=None,
            second_score=None,
        )
    top_score = candidates[0].suspicion_score
    second_score = candidates[1].suspicion_score if len(candidates) > 1 else None
    if top_score < policy.minimum_score:
        return BaselineAbstention(
            policy=policy,
            reason=AbstentionReason.WEAK_EVIDENCE,
            signal_evaluations=signal_evaluations,
            evaluated_candidates=candidates,
            eligible_signal_count=len(candidates),
            top_score=top_score,
            second_score=second_score,
        )
    lead = math.inf if second_score is None else top_score - second_score
    if second_score is not None and lead < policy.minimum_margin:
        return BaselineAbstention(
            policy=policy,
            reason=AbstentionReason.AMBIGUOUS_EVIDENCE,
            signal_evaluations=signal_evaluations,
            evaluated_candidates=candidates,
            eligible_signal_count=len(candidates),
            top_score=top_score,
            second_score=second_score,
        )
    return BaselineRanking(
        policy=policy,
        signal_evaluations=signal_evaluations,
        candidates=candidates,
        lead=lead,
    )
