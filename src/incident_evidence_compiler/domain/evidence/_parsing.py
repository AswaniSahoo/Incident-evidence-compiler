"""Validation primitives that reconstruct trusted domain objects from untrusted input."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import NoReturn

from ..baseline import BaselinePolicy, SignalEvaluation, SuspicionCandidate
from ..errors import InvalidEvidenceLedgerError
from ..identifiers import IncidentId, RunId, TenantId
from ..incidents import IncidentWindow
from ..metrics import SignalKey


def _invalid() -> NoReturn:
    raise InvalidEvidenceLedgerError


def _finite_float(value: object, *, nonnegative: bool = False, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _invalid()
    try:
        converted = float(value)
    except (OverflowError, TypeError, ValueError):
        _invalid()
    if not math.isfinite(converted):
        _invalid()
    if positive and converted <= 0.0:
        _invalid()
    if nonnegative and converted < 0.0:
        _invalid()
    return converted


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _invalid()
    return value


def _identifier[IdentifierT: (TenantId, IncidentId, RunId)](
    identifier: object, expected_type: type[IdentifierT]
) -> IdentifierT:
    if type(identifier) is not expected_type:
        _invalid()
    try:
        value = identifier.value
    except Exception:
        _invalid()
    if not isinstance(value, str) or not value.strip():
        _invalid()
    try:
        return expected_type(value)
    except Exception:
        _invalid()


def _signal_key(value: object) -> SignalKey:
    if type(value) is not SignalKey:
        _invalid()
    try:
        raw = value.value
    except Exception:
        _invalid()
    if not isinstance(raw, str) or not raw.strip():
        _invalid()
    try:
        return SignalKey(raw)
    except Exception:
        _invalid()


def _policy(value: object) -> BaselinePolicy:
    if not isinstance(value, BaselinePolicy):
        _invalid()
    minimum_points = value.minimum_points_per_window
    if (
        isinstance(minimum_points, bool)
        or not isinstance(minimum_points, int)
        or minimum_points < 1
    ):
        _invalid()
    minimum_score = _finite_float(value.minimum_score, nonnegative=True)
    minimum_margin = _finite_float(value.minimum_margin, nonnegative=True)
    relative_floor = _finite_float(value.relative_scale_floor, nonnegative=True)
    return BaselinePolicy(minimum_points, minimum_score, minimum_margin, relative_floor)


def _window(value: object) -> IncidentWindow:
    if type(value) is not IncidentWindow:
        _invalid()
    try:
        timestamps = (value.start, value.injection, value.end)
        if not all(isinstance(item, datetime) and item.tzinfo is not None for item in timestamps):
            _invalid()
        if any(item.utcoffset() is None for item in timestamps):
            _invalid()
        normalized = tuple(item.astimezone(UTC) for item in timestamps)
        if not normalized[0] <= normalized[1] < normalized[2]:
            _invalid()
        return IncidentWindow(*normalized)
    except InvalidEvidenceLedgerError:
        raise
    except Exception:
        raise InvalidEvidenceLedgerError from None


def _candidate(
    value: object,
    evaluation: SignalEvaluation,
    policy: BaselinePolicy,
) -> SuspicionCandidate:
    if not isinstance(value, SuspicionCandidate):
        _invalid()
    signal_key = _signal_key(value.signal_key)
    pre_count = _count(value.pre_point_count)
    post_count = _count(value.post_point_count)
    pre_median = _finite_float(value.pre_median)
    post_median = _finite_float(value.post_median)
    pre_mad = _finite_float(value.pre_mad, nonnegative=True)
    absolute_floor = _finite_float(value.absolute_scale_floor, positive=True)
    relative_floor = _finite_float(value.relative_scale_floor, nonnegative=True)
    scale = _finite_float(value.scale, positive=True)
    signed_score = _finite_float(value.signed_score)
    suspicion_score = _finite_float(value.suspicion_score, nonnegative=True)

    if (
        signal_key != evaluation.signal_key
        or pre_count != evaluation.pre_point_count
        or post_count != evaluation.post_point_count
        or absolute_floor != evaluation.absolute_scale_floor
        or relative_floor != policy.relative_scale_floor
    ):
        _invalid()

    robust_scale = 1.4826 * pre_mad
    relative_scale = relative_floor * max(abs(pre_median), absolute_floor)
    expected_scale = max(robust_scale, absolute_floor, relative_scale)
    try:
        expected_signed_score = (post_median - pre_median) / expected_scale
    except (OverflowError, ZeroDivisionError):
        _invalid()
    if not math.isfinite(robust_scale) or not math.isfinite(relative_scale):
        _invalid()
    if not math.isfinite(expected_signed_score):
        _invalid()
    if (
        scale != expected_scale
        or signed_score != expected_signed_score
        or suspicion_score != abs(signed_score)
    ):
        _invalid()

    return SuspicionCandidate(
        signal_key=signal_key,
        pre_point_count=pre_count,
        post_point_count=post_count,
        pre_median=pre_median,
        post_median=post_median,
        pre_mad=pre_mad,
        absolute_scale_floor=absolute_floor,
        relative_scale_floor=relative_floor,
        scale=scale,
        signed_score=signed_score,
        suspicion_score=suspicion_score,
    )


def _evaluations(
    values: object,
    policy: BaselinePolicy,
) -> tuple[tuple[SignalEvaluation, ...], tuple[SuspicionCandidate, ...]]:
    if not isinstance(values, tuple):
        _invalid()
    copied: list[SignalEvaluation] = []
    candidates: list[SuspicionCandidate] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, SignalEvaluation):
            _invalid()
        signal_key = _signal_key(value.signal_key)
        if signal_key.value in seen:
            _invalid()
        seen.add(signal_key.value)
        absolute_floor = _finite_float(value.absolute_scale_floor, positive=True)
        pre_count = _count(value.pre_point_count)
        post_count = _count(value.post_point_count)
        if not isinstance(value.eligible, bool):
            _invalid()
        expected_eligible = (
            pre_count >= policy.minimum_points_per_window
            and post_count >= policy.minimum_points_per_window
        )
        if value.eligible != expected_eligible or (value.candidate is not None) != value.eligible:
            _invalid()
        shell = SignalEvaluation(
            signal_key=signal_key,
            absolute_scale_floor=absolute_floor,
            pre_point_count=pre_count,
            post_point_count=post_count,
            eligible=value.eligible,
            candidate=None,
        )
        candidate = _candidate(value.candidate, shell, policy) if value.eligible else None
        evaluation = SignalEvaluation(
            signal_key=signal_key,
            absolute_scale_floor=absolute_floor,
            pre_point_count=pre_count,
            post_point_count=post_count,
            eligible=value.eligible,
            candidate=candidate,
        )
        copied.append(evaluation)
        if candidate is not None:
            candidates.append(candidate)
    ordered_evaluations = tuple(sorted(copied, key=lambda item: item.signal_key.value))
    ordered_candidates = tuple(
        sorted(candidates, key=lambda item: (-item.suspicion_score, item.signal_key.value))
    )
    return ordered_evaluations, ordered_candidates


def _optional_score(value: object) -> float | None:
    return None if value is None else _finite_float(value, nonnegative=True)
