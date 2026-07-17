"""Reconstruction of the aggregate baseline decision snapshot."""

from __future__ import annotations

import math

from ..baseline import (
    AbstentionReason,
    BaselineAbstention,
    BaselinePolicy,
    BaselineRanking,
    BaselineResult,
    SuspicionCandidate,
)
from ._parsing import _count, _finite_float, _invalid, _optional_score, _signal_key
from .types import MetricShiftDecision, MetricShiftDecisionKind


def _decision(
    result: BaselineResult,
    policy: BaselinePolicy,
    candidates: tuple[SuspicionCandidate, ...],
) -> MetricShiftDecision:
    candidate_keys = tuple(candidate.signal_key for candidate in candidates)
    top_score = candidates[0].suspicion_score if candidates else None
    second_score = candidates[1].suspicion_score if len(candidates) > 1 else None

    if isinstance(result, BaselineRanking):
        if not isinstance(result.candidates, tuple) or result.candidates != candidates:
            _invalid()
        if not candidates or top_score is None or top_score < policy.minimum_score:
            _invalid()
        if len(candidates) == 1:
            if not isinstance(result.lead, float) or not math.isinf(result.lead) or result.lead < 0:
                _invalid()
            lead = None
        else:
            lead = _finite_float(result.lead, nonnegative=True)
            expected_lead = candidates[0].suspicion_score - candidates[1].suspicion_score
            if lead != expected_lead or lead < policy.minimum_margin:
                _invalid()
        return MetricShiftDecision(
            kind=MetricShiftDecisionKind.RANKING,
            abstention_reason=None,
            candidate_signal_keys=candidate_keys,
            eligible_signal_count=len(candidates),
            top_score=top_score,
            second_score=second_score,
            lead=lead,
        )

    if not isinstance(result, BaselineAbstention):
        _invalid()
    if (
        not isinstance(result.evaluated_candidates, tuple)
        or result.evaluated_candidates != candidates
    ):
        _invalid()
    eligible_count = _count(result.eligible_signal_count)
    supplied_top = _optional_score(result.top_score)
    supplied_second = _optional_score(result.second_score)
    if (
        eligible_count != len(candidates)
        or supplied_top != top_score
        or supplied_second != second_score
        or not isinstance(result.reason, AbstentionReason)
    ):
        _invalid()

    if not candidates:
        expected_reason = AbstentionReason.INSUFFICIENT_EVIDENCE
    elif top_score is not None and top_score < policy.minimum_score:
        expected_reason = AbstentionReason.WEAK_EVIDENCE
    elif (
        second_score is not None
        and top_score is not None
        and top_score - second_score < policy.minimum_margin
    ):
        expected_reason = AbstentionReason.AMBIGUOUS_EVIDENCE
    else:
        _invalid()
    if result.reason is not expected_reason:
        _invalid()
    return MetricShiftDecision(
        kind=MetricShiftDecisionKind.ABSTENTION,
        abstention_reason=result.reason,
        candidate_signal_keys=candidate_keys,
        eligible_signal_count=eligible_count,
        top_score=top_score,
        second_score=second_score,
        lead=None,
    )


def _ledger_decision(
    value: object,
    policy: BaselinePolicy,
    candidates: tuple[SuspicionCandidate, ...],
) -> MetricShiftDecision:
    if type(value) is not MetricShiftDecision:
        _invalid()
    if type(value.kind) is not MetricShiftDecisionKind:
        _invalid()
    if not isinstance(value.candidate_signal_keys, tuple):
        _invalid()
    candidate_keys = tuple(_signal_key(key) for key in value.candidate_signal_keys)
    expected_keys = tuple(candidate.signal_key for candidate in candidates)
    eligible_count = _count(value.eligible_signal_count)
    top_score = candidates[0].suspicion_score if candidates else None
    second_score = candidates[1].suspicion_score if len(candidates) > 1 else None
    supplied_top = _optional_score(value.top_score)
    supplied_second = _optional_score(value.second_score)
    if (
        candidate_keys != expected_keys
        or eligible_count != len(candidates)
        or supplied_top != top_score
        or supplied_second != second_score
    ):
        _invalid()

    if value.kind is MetricShiftDecisionKind.RANKING:
        if value.abstention_reason is not None or not candidates or top_score is None:
            _invalid()
        if top_score < policy.minimum_score:
            _invalid()
        if len(candidates) == 1:
            if value.lead is not None or second_score is not None:
                _invalid()
            lead = None
        else:
            lead = _finite_float(value.lead, nonnegative=True)
            expected_lead = candidates[0].suspicion_score - candidates[1].suspicion_score
            if lead != expected_lead or lead < policy.minimum_margin:
                _invalid()
        reason = None
    else:
        if value.kind is not MetricShiftDecisionKind.ABSTENTION:
            _invalid()
        if type(value.abstention_reason) is not AbstentionReason or value.lead is not None:
            _invalid()
        if not candidates:
            expected_reason = AbstentionReason.INSUFFICIENT_EVIDENCE
        elif top_score is not None and top_score < policy.minimum_score:
            expected_reason = AbstentionReason.WEAK_EVIDENCE
        elif (
            second_score is not None
            and top_score is not None
            and top_score - second_score < policy.minimum_margin
        ):
            expected_reason = AbstentionReason.AMBIGUOUS_EVIDENCE
        else:
            _invalid()
        if value.abstention_reason is not expected_reason:
            _invalid()
        reason = expected_reason
        lead = None

    return MetricShiftDecision(
        kind=value.kind,
        abstention_reason=reason,
        candidate_signal_keys=candidate_keys,
        eligible_signal_count=eligible_count,
        top_score=top_score,
        second_score=second_score,
        lead=lead,
    )
