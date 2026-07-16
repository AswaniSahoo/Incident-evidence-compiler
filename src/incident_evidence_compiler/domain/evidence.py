"""Immutable, content-bound metric-shift evidence ledgers."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, NoReturn

from .baseline import (
    AbstentionReason,
    BaselineAbstention,
    BaselinePolicy,
    BaselineRanking,
    BaselineResult,
    SignalEvaluation,
    SuspicionCandidate,
)
from .errors import InvalidEvidenceLedgerError
from .identifiers import EvidenceId, IncidentId, RunId, TenantId
from .incidents import IncidentWindow
from .metrics import SignalKey

SCHEMA_VERSION = "metric-evidence-ledger.v1"
_ID_DOMAIN = b"incident-evidence-compiler.metric-shift-evidence.v1\x00"


class MetricShiftDecisionKind(StrEnum):
    """The aggregate Phase 1 decision retained as diagnostic context."""

    RANKING = "ranking"
    ABSTENTION = "abstention"


@dataclass(frozen=True, slots=True, repr=False)
class MetricShiftDecision:
    """A finite, immutable snapshot of the aggregate baseline decision."""

    kind: MetricShiftDecisionKind
    abstention_reason: AbstentionReason | None
    candidate_signal_keys: tuple[SignalKey, ...]
    eligible_signal_count: int
    top_score: float | None
    second_score: float | None
    lead: float | None

    def __repr__(self) -> str:
        return (
            f"MetricShiftDecision(kind='{self.kind.value}', "
            f"candidate_count={len(self.candidate_signal_keys)})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class MetricShiftEvidence:
    """Replayable evidence for exactly one evaluated metric signal."""

    evidence_id: EvidenceId
    signal_key: SignalKey
    pre_point_count: int
    post_point_count: int
    eligible: bool
    absolute_scale_floor: float
    relative_scale_floor: float
    candidate: SuspicionCandidate | None

    def __repr__(self) -> str:
        return f"MetricShiftEvidence(eligible={self.eligible})"


@dataclass(frozen=True, slots=True, repr=False)
class MetricEvidenceLedger:
    """One immutable Phase 1 baseline bound to an exact incident run context."""

    schema_version: str
    tenant_id: TenantId
    incident_id: IncidentId
    run_id: RunId
    window: IncidentWindow
    policy: BaselinePolicy
    decision: MetricShiftDecision
    entries: tuple[MetricShiftEvidence, ...]

    def __repr__(self) -> str:
        return (
            f"MetricEvidenceLedger(schema_version='{self.schema_version}', "
            f"entry_count={len(self.entries)}, decision='{self.decision.kind.value}')"
        )


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


def _hex(value: float | None) -> str | None:
    return None if value is None else value.hex()


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _policy_payload(policy: BaselinePolicy) -> dict[str, object]:
    return {
        "minimum_margin": policy.minimum_margin.hex(),
        "minimum_points_per_window": policy.minimum_points_per_window,
        "minimum_score": policy.minimum_score.hex(),
        "relative_scale_floor": policy.relative_scale_floor.hex(),
    }


def _decision_payload(decision: MetricShiftDecision) -> dict[str, object]:
    return {
        "abstention_reason": (
            None if decision.abstention_reason is None else decision.abstention_reason.value
        ),
        "candidate_signal_keys": [key.value for key in decision.candidate_signal_keys],
        "eligible_signal_count": decision.eligible_signal_count,
        "kind": decision.kind.value,
        "lead": _hex(decision.lead),
        "second_score": _hex(decision.second_score),
        "top_score": _hex(decision.top_score),
    }


def _candidate_payload(candidate: SuspicionCandidate | None) -> dict[str, object] | None:
    if candidate is None:
        return None
    return {
        "absolute_scale_floor": candidate.absolute_scale_floor.hex(),
        "post_median": candidate.post_median.hex(),
        "post_point_count": candidate.post_point_count,
        "pre_mad": candidate.pre_mad.hex(),
        "pre_median": candidate.pre_median.hex(),
        "pre_point_count": candidate.pre_point_count,
        "relative_scale_floor": candidate.relative_scale_floor.hex(),
        "scale": candidate.scale.hex(),
        "signal_key": candidate.signal_key.value,
        "signed_score": candidate.signed_score.hex(),
        "suspicion_score": candidate.suspicion_score.hex(),
    }


def _entry_payload(
    tenant_id: TenantId,
    incident_id: IncidentId,
    run_id: RunId,
    window: IncidentWindow,
    policy: BaselinePolicy,
    decision: MetricShiftDecision,
    evaluation: SignalEvaluation,
) -> dict[str, Any]:
    return {
        "absolute_scale_floor": evaluation.absolute_scale_floor.hex(),
        "candidate": _candidate_payload(evaluation.candidate),
        "decision": _decision_payload(decision),
        "eligible": evaluation.eligible,
        "incident_id": incident_id.value,
        "incident_window": {
            "end": _timestamp(window.end),
            "injection": _timestamp(window.injection),
            "start": _timestamp(window.start),
        },
        "policy": _policy_payload(policy),
        "post_point_count": evaluation.post_point_count,
        "pre_point_count": evaluation.pre_point_count,
        "relative_scale_floor": policy.relative_scale_floor.hex(),
        "run_id": run_id.value,
        "schema_version": SCHEMA_VERSION,
        "signal_key": evaluation.signal_key.value,
        "tenant_id": tenant_id.value,
    }


def _evidence_id(payload: dict[str, Any]) -> EvidenceId:
    try:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(_ID_DOMAIN + canonical).hexdigest()
        return EvidenceId(f"sha256:{digest}")
    except Exception:
        raise InvalidEvidenceLedgerError from None


def _evidence_identifier(value: object) -> EvidenceId:
    if type(value) is not EvidenceId:
        _invalid()
    raw = value.value
    prefix, separator, digest = raw.partition(":") if isinstance(raw, str) else ("", "", "")
    if (
        separator != ":"
        or prefix != "sha256"
        or len(digest) != 64
        or digest != digest.lower()
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        _invalid()
    return EvidenceId(raw)


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


def _validated_metric_evidence_ledger(value: object) -> MetricEvidenceLedger:
    if type(value) is not MetricEvidenceLedger or value.schema_version != SCHEMA_VERSION:
        _invalid()
    tenant = _identifier(value.tenant_id, TenantId)
    incident = _identifier(value.incident_id, IncidentId)
    run = _identifier(value.run_id, RunId)
    normalized_window = _window(value.window)
    policy = _policy(value.policy)
    if not isinstance(value.entries, tuple):
        _invalid()

    supplied_ids: list[EvidenceId] = []
    evaluations: list[SignalEvaluation] = []
    supplied_order: list[str] = []
    for entry in value.entries:
        if type(entry) is not MetricShiftEvidence:
            _invalid()
        evidence_id = _evidence_identifier(entry.evidence_id)
        signal_key = _signal_key(entry.signal_key)
        pre_count = _count(entry.pre_point_count)
        post_count = _count(entry.post_point_count)
        if type(entry.eligible) is not bool:
            _invalid()
        absolute_floor = _finite_float(entry.absolute_scale_floor, positive=True)
        relative_floor = _finite_float(entry.relative_scale_floor, nonnegative=True)
        expected_eligible = (
            pre_count >= policy.minimum_points_per_window
            and post_count >= policy.minimum_points_per_window
        )
        if (
            relative_floor != policy.relative_scale_floor
            or entry.eligible != expected_eligible
            or (entry.candidate is not None) != entry.eligible
        ):
            _invalid()
        shell = SignalEvaluation(
            signal_key=signal_key,
            absolute_scale_floor=absolute_floor,
            pre_point_count=pre_count,
            post_point_count=post_count,
            eligible=entry.eligible,
            candidate=None,
        )
        candidate = _candidate(entry.candidate, shell, policy) if entry.eligible else None
        evaluations.append(
            SignalEvaluation(
                signal_key=signal_key,
                absolute_scale_floor=absolute_floor,
                pre_point_count=pre_count,
                post_point_count=post_count,
                eligible=entry.eligible,
                candidate=candidate,
            )
        )
        supplied_ids.append(evidence_id)
        supplied_order.append(signal_key.value)

    ordered_evaluations, candidates = _evaluations(tuple(evaluations), policy)
    if supplied_order != [evaluation.signal_key.value for evaluation in ordered_evaluations]:
        _invalid()
    decision = _ledger_decision(value.decision, policy, candidates)
    entries = tuple(
        MetricShiftEvidence(
            evidence_id=_evidence_id(
                _entry_payload(
                    tenant,
                    incident,
                    run,
                    normalized_window,
                    policy,
                    decision,
                    evaluation,
                )
            ),
            signal_key=evaluation.signal_key,
            pre_point_count=evaluation.pre_point_count,
            post_point_count=evaluation.post_point_count,
            eligible=evaluation.eligible,
            absolute_scale_floor=evaluation.absolute_scale_floor,
            relative_scale_floor=policy.relative_scale_floor,
            candidate=evaluation.candidate,
        )
        for evaluation in ordered_evaluations
    )
    if tuple(entry.evidence_id for entry in entries) != tuple(supplied_ids):
        _invalid()
    return MetricEvidenceLedger(
        schema_version=SCHEMA_VERSION,
        tenant_id=tenant,
        incident_id=incident,
        run_id=run,
        window=normalized_window,
        policy=policy,
        decision=decision,
        entries=entries,
    )


def validate_metric_evidence_ledger(value: object) -> MetricEvidenceLedger:
    """Deeply reconstruct a ledger and verify every content-bound evidence ID."""
    try:
        return _validated_metric_evidence_ledger(value)
    except InvalidEvidenceLedgerError:
        raise
    except Exception:
        raise InvalidEvidenceLedgerError from None


def _compile_metric_shift_ledger(
    tenant_id: TenantId,
    incident_id: IncidentId,
    run_id: RunId,
    window: IncidentWindow,
    baseline_result: BaselineResult,
) -> MetricEvidenceLedger:
    """Validate and bind a Phase 1 result without repairing forged state."""
    tenant = _identifier(tenant_id, TenantId)
    incident = _identifier(incident_id, IncidentId)
    run = _identifier(run_id, RunId)
    normalized_window = _window(window)
    if not isinstance(baseline_result, (BaselineRanking, BaselineAbstention)):
        _invalid()
    frozen_policy = _policy(baseline_result.policy)
    evaluations, candidates = _evaluations(
        baseline_result.signal_evaluations,
        frozen_policy,
    )
    decision = _decision(baseline_result, frozen_policy, candidates)
    entries = tuple(
        MetricShiftEvidence(
            evidence_id=_evidence_id(
                _entry_payload(
                    tenant,
                    incident,
                    run,
                    normalized_window,
                    frozen_policy,
                    decision,
                    evaluation,
                )
            ),
            signal_key=evaluation.signal_key,
            pre_point_count=evaluation.pre_point_count,
            post_point_count=evaluation.post_point_count,
            eligible=evaluation.eligible,
            absolute_scale_floor=evaluation.absolute_scale_floor,
            relative_scale_floor=frozen_policy.relative_scale_floor,
            candidate=evaluation.candidate,
        )
        for evaluation in evaluations
    )
    ledger = MetricEvidenceLedger(
        schema_version=SCHEMA_VERSION,
        tenant_id=tenant,
        incident_id=incident,
        run_id=run,
        window=normalized_window,
        policy=frozen_policy,
        decision=decision,
        entries=entries,
    )
    return validate_metric_evidence_ledger(ledger)


def compile_metric_shift_ledger(
    tenant_id: TenantId,
    incident_id: IncidentId,
    run_id: RunId,
    window: IncidentWindow,
    baseline_result: BaselineResult,
) -> MetricEvidenceLedger:
    """Compile trusted Phase 1 types and normalize every malformed object failure."""
    if type(baseline_result) not in {BaselineRanking, BaselineAbstention}:
        raise InvalidEvidenceLedgerError
    try:
        return _compile_metric_shift_ledger(
            tenant_id,
            incident_id,
            run_id,
            window,
            baseline_result,
        )
    except InvalidEvidenceLedgerError:
        raise
    except Exception:
        raise InvalidEvidenceLedgerError from None
