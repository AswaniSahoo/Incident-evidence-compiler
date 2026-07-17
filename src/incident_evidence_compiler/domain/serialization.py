"""Canonical, leakage-bounded JSON for evidence and verification artifacts."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import NoReturn, cast

from .baseline import AbstentionReason, BaselinePolicy, SuspicionCandidate
from .change_evidence import (
    SCHEMA_VERSION as CHANGE_LEDGER_SCHEMA_VERSION,
)
from .change_evidence import (
    ChangeEventEvidence,
    ChangeEventLedger,
    ChangePhase,
    validate_change_event_ledger,
)
from .change_hypotheses import ChangePhaseConstraint
from .change_verifier import (
    ChangeHypothesisVerificationResult,
    ChangePredicateVerificationResult,
    ChangeUnknownReason,
)
from .changes import ChangeEventKey, ChangeKind
from .errors import (
    CanonicalSerializationError,
    InvalidChangeEventLedgerError,
    InvalidEvidenceLedgerError,
)
from .evidence import (
    SCHEMA_VERSION as LEDGER_SCHEMA_VERSION,
)
from .evidence import (
    MetricEvidenceLedger,
    MetricShiftDecision,
    MetricShiftDecisionKind,
    MetricShiftEvidence,
    validate_metric_evidence_ledger,
)
from .hypotheses import HypothesisComposition
from .identifiers import EvidenceId, IncidentId, RunId, TenantId
from .incidents import IncidentWindow
from .metrics import SignalKey
from .verifier import (
    HypothesisVerificationResult,
    ObservedDirection,
    PredicateVerificationResult,
    UnknownReason,
    VerificationVerdict,
)

VERIFICATION_SCHEMA_VERSION = "metric-hypothesis-verification.v1"
CHANGE_VERIFICATION_SCHEMA_VERSION = "change-cooccurrence-verification.v1"


def _fail() -> NoReturn:
    raise CanonicalSerializationError


def _exact[T](value: object, expected: type[T]) -> T:
    if type(value) is not expected:
        _fail()
    return value


def _text(value: object) -> str:
    text = _exact(value, str)
    if not text.strip():
        _fail()
    return text


def _count(value: object, *, positive: bool = False) -> int:
    count = _exact(value, int)
    if count < (1 if positive else 0):
        _fail()
    return count


def _finite_hex(value: object, *, nonnegative: bool = False, positive: bool = False) -> str:
    number = _exact(value, float)
    if not math.isfinite(number):
        _fail()
    if nonnegative and number < 0.0:
        _fail()
    if positive and number <= 0.0:
        _fail()
    return number.hex()


def _optional_finite_hex(
    value: object,
    *,
    nonnegative: bool = False,
) -> str | None:
    if value is None:
        return None
    return _finite_hex(value, nonnegative=nonnegative)


def _enum_value[T](value: object, expected: type[T]) -> str:
    member = _exact(value, expected)
    if not isinstance(member, StrEnum):
        _fail()
    return member.value


def _identifier[T](value: object, expected: type[T]) -> str:
    identifier = _exact(value, expected)
    raw = getattr(identifier, "value", None)
    return _text(raw)


def _evidence_id(value: object) -> str:
    raw = _identifier(value, EvidenceId)
    prefix, separator, digest = raw.partition(":")
    if (
        separator != ":"
        or prefix != "sha256"
        or len(digest) != 64
        or digest != digest.lower()
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        _fail()
    return raw


def _timestamp(value: object) -> str:
    instant = _exact(value, datetime)
    if instant.tzinfo is not UTC:
        _fail()
    return instant.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _window_payload(value: object) -> dict[str, object]:
    window = _exact(value, IncidentWindow)
    if not window.start <= window.injection < window.end:
        _fail()
    return {
        "end": _timestamp(window.end),
        "injection": _timestamp(window.injection),
        "start": _timestamp(window.start),
    }


def _policy_payload(value: object) -> dict[str, object]:
    policy = _exact(value, BaselinePolicy)
    return {
        "minimum_margin": _finite_hex(policy.minimum_margin, nonnegative=True),
        "minimum_points_per_window": _count(policy.minimum_points_per_window, positive=True),
        "minimum_score": _finite_hex(policy.minimum_score, nonnegative=True),
        "relative_scale_floor": _finite_hex(
            policy.relative_scale_floor,
            nonnegative=True,
        ),
    }


def _signal_key(value: object) -> str:
    key = _exact(value, SignalKey)
    return _text(key.value)


def _signal_keys(values: object) -> list[str]:
    keys = _exact(values, tuple)
    serialized = [_signal_key(value) for value in keys]
    if len(set(serialized)) != len(serialized):
        _fail()
    return serialized


def _decision_payload(value: object) -> dict[str, object]:
    decision = _exact(value, MetricShiftDecision)
    kind = _enum_value(decision.kind, MetricShiftDecisionKind)
    if decision.abstention_reason is None:
        abstention_reason = None
    else:
        abstention_reason = _enum_value(decision.abstention_reason, AbstentionReason)
    if (kind == MetricShiftDecisionKind.RANKING.value) != (abstention_reason is None):
        _fail()
    candidate_signal_keys = _signal_keys(decision.candidate_signal_keys)
    eligible_signal_count = _count(decision.eligible_signal_count)
    if eligible_signal_count != len(candidate_signal_keys):
        _fail()
    return {
        "abstention_reason": abstention_reason,
        "candidate_signal_keys": candidate_signal_keys,
        "eligible_signal_count": eligible_signal_count,
        "kind": kind,
        "lead": _optional_finite_hex(decision.lead, nonnegative=True),
        "second_score": _optional_finite_hex(decision.second_score, nonnegative=True),
        "top_score": _optional_finite_hex(decision.top_score, nonnegative=True),
    }


def _candidate_payload(value: object) -> dict[str, object]:
    candidate = _exact(value, SuspicionCandidate)
    return {
        "absolute_scale_floor": _finite_hex(candidate.absolute_scale_floor, positive=True),
        "post_median": _finite_hex(candidate.post_median),
        "post_point_count": _count(candidate.post_point_count),
        "pre_mad": _finite_hex(candidate.pre_mad, nonnegative=True),
        "pre_median": _finite_hex(candidate.pre_median),
        "pre_point_count": _count(candidate.pre_point_count),
        "relative_scale_floor": _finite_hex(
            candidate.relative_scale_floor,
            nonnegative=True,
        ),
        "scale": _finite_hex(candidate.scale, positive=True),
        "signal_key": _signal_key(candidate.signal_key),
        "signed_score": _finite_hex(candidate.signed_score),
        "suspicion_score": _finite_hex(candidate.suspicion_score, nonnegative=True),
    }


def _entry_payload(value: object) -> dict[str, object]:
    entry = _exact(value, MetricShiftEvidence)
    eligible = _exact(entry.eligible, bool)
    candidate = None if entry.candidate is None else _candidate_payload(entry.candidate)
    signal_key = _signal_key(entry.signal_key)
    pre_point_count = _count(entry.pre_point_count)
    post_point_count = _count(entry.post_point_count)
    absolute_scale_floor = _finite_hex(entry.absolute_scale_floor, positive=True)
    relative_scale_floor = _finite_hex(entry.relative_scale_floor, nonnegative=True)
    if eligible != (candidate is not None):
        _fail()
    if candidate is not None and (
        candidate["signal_key"] != signal_key
        or candidate["pre_point_count"] != pre_point_count
        or candidate["post_point_count"] != post_point_count
        or candidate["absolute_scale_floor"] != absolute_scale_floor
        or candidate["relative_scale_floor"] != relative_scale_floor
    ):
        _fail()
    return {
        "absolute_scale_floor": absolute_scale_floor,
        "candidate": candidate,
        "eligible": eligible,
        "evidence_id": _evidence_id(entry.evidence_id),
        "post_point_count": post_point_count,
        "pre_point_count": pre_point_count,
        "relative_scale_floor": relative_scale_floor,
        "signal_key": signal_key,
    }


def _entries_payload(value: object) -> list[dict[str, object]]:
    entries = _exact(value, tuple)
    serialized = [_entry_payload(entry) for entry in entries]
    keys = [cast(str, entry["signal_key"]) for entry in serialized]
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        _fail()
    return serialized


def _evidence_ids(value: object) -> list[str]:
    identifiers = _exact(value, tuple)
    return [_evidence_id(identifier) for identifier in identifiers]


def _optional_reason(value: object) -> str | None:
    if value is None:
        return None
    return _enum_value(value, UnknownReason)


def _optional_direction(value: object) -> str | None:
    if value is None:
        return None
    return _enum_value(value, ObservedDirection)


def _predicate_result_payload(value: object) -> dict[str, object]:
    result = _exact(value, PredicateVerificationResult)
    verdict = _enum_value(result.verdict, VerificationVerdict)
    reason = _optional_reason(result.reason)
    observed_direction = _optional_direction(result.observed_direction)
    supporting = _evidence_ids(result.supporting_evidence_ids)
    contradicting = _evidence_ids(result.contradicting_evidence_ids)
    if set(supporting) & set(contradicting):
        _fail()
    if verdict == VerificationVerdict.UNKNOWN.value:
        if reason is None or supporting or contradicting:
            _fail()
        directionless_reasons = {
            UnknownReason.CONTEXT_MISMATCH.value,
            UnknownReason.CAUSAL_CLAIM_NOT_VERIFIABLE.value,
            UnknownReason.SIGNAL_NOT_FOUND.value,
            UnknownReason.INSUFFICIENT_EVIDENCE.value,
            UnknownReason.NO_DIRECTIONAL_SHIFT.value,
        }
        if reason in directionless_reasons and observed_direction is not None:
            _fail()
        if reason == UnknownReason.WEAK_EVIDENCE.value and observed_direction is None:
            _fail()
    elif reason is not None or observed_direction is None:
        _fail()
    elif verdict == VerificationVerdict.SUPPORTED.value:
        if not supporting or contradicting:
            _fail()
    elif verdict == VerificationVerdict.REFUTED.value:
        if supporting or not contradicting:
            _fail()
    else:
        _fail()
    return {
        "contradicting_evidence_ids": contradicting,
        "minimum_score": _finite_hex(result.minimum_score, nonnegative=True),
        "observed_direction": observed_direction,
        "predicate_id": _text(result.predicate_id),
        "reason": reason,
        "supporting_evidence_ids": supporting,
        "verdict": verdict,
    }


def _predicate_results(value: object) -> list[dict[str, object]]:
    results = _exact(value, tuple)
    serialized = [_predicate_result_payload(result) for result in results]
    predicate_ids = [cast(str, result["predicate_id"]) for result in serialized]
    if len(set(predicate_ids)) != len(predicate_ids):
        _fail()
    return serialized


def _ledger_payload(value: object) -> dict[str, object]:
    try:
        ledger = validate_metric_evidence_ledger(value)
    except InvalidEvidenceLedgerError:
        _fail()
    schema_version = _text(ledger.schema_version)
    if schema_version != LEDGER_SCHEMA_VERSION:
        _fail()
    policy = _policy_payload(ledger.policy)
    entries = _entries_payload(ledger.entries)
    if any(entry["relative_scale_floor"] != policy["relative_scale_floor"] for entry in entries):
        _fail()
    return {
        "decision": _decision_payload(ledger.decision),
        "entries": entries,
        "incident_id": _identifier(ledger.incident_id, IncidentId),
        "incident_window": _window_payload(ledger.window),
        "policy": policy,
        "run_id": _identifier(ledger.run_id, RunId),
        "schema_version": schema_version,
        "tenant_id": _identifier(ledger.tenant_id, TenantId),
    }


def _verification_payload(value: object) -> dict[str, object]:
    result = _exact(value, HypothesisVerificationResult)
    composition = _enum_value(result.composition, HypothesisComposition)
    verdict = _enum_value(result.verdict, VerificationVerdict)
    reason = _optional_reason(result.reason)
    predicates = _predicate_results(result.predicate_results)
    if not predicates:
        _fail()
    supporting = _evidence_ids(result.supporting_evidence_ids)
    contradicting = _evidence_ids(result.contradicting_evidence_ids)
    expected_supporting = [
        evidence_id
        for predicate in predicates
        for evidence_id in cast(list[str], predicate["supporting_evidence_ids"])
    ]
    expected_contradicting = [
        evidence_id
        for predicate in predicates
        for evidence_id in cast(list[str], predicate["contradicting_evidence_ids"])
    ]
    if supporting != expected_supporting or contradicting != expected_contradicting:
        _fail()

    child_verdicts = tuple(cast(str, predicate["verdict"]) for predicate in predicates)
    if composition == HypothesisComposition.ALL.value:
        expected_verdict = (
            VerificationVerdict.REFUTED.value
            if VerificationVerdict.REFUTED.value in child_verdicts
            else VerificationVerdict.UNKNOWN.value
            if VerificationVerdict.UNKNOWN.value in child_verdicts
            else VerificationVerdict.SUPPORTED.value
        )
    else:
        expected_verdict = (
            VerificationVerdict.SUPPORTED.value
            if VerificationVerdict.SUPPORTED.value in child_verdicts
            else VerificationVerdict.UNKNOWN.value
            if VerificationVerdict.UNKNOWN.value in child_verdicts
            else VerificationVerdict.REFUTED.value
        )
    if verdict != expected_verdict:
        _fail()

    gate_reasons = {
        UnknownReason.CONTEXT_MISMATCH.value,
        UnknownReason.CAUSAL_CLAIM_NOT_VERIFIABLE.value,
    }
    if reason is not None:
        if reason not in gate_reasons or verdict != VerificationVerdict.UNKNOWN.value:
            _fail()
        if supporting or contradicting:
            _fail()
        if any(
            predicate["verdict"] != VerificationVerdict.UNKNOWN.value
            or predicate["reason"] != reason
            or predicate["observed_direction"] is not None
            or predicate["supporting_evidence_ids"]
            or predicate["contradicting_evidence_ids"]
            for predicate in predicates
        ):
            _fail()
    elif any(predicate["reason"] in gate_reasons for predicate in predicates):
        _fail()

    return {
        "composition": composition,
        "contradicting_evidence_ids": contradicting,
        "hypothesis_id": _text(result.hypothesis_id),
        "predicate_results": predicates,
        "reason": reason,
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "supporting_evidence_ids": supporting,
        "verdict": verdict,
    }


def _canonical_json(payload: dict[str, object]) -> str:
    try:
        serialized = (
            json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        serialized.encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError):
        _fail()
    return serialized


def ledger_json(ledger: MetricEvidenceLedger) -> str:
    """Serialize one validated metric-evidence ledger canonically."""
    try:
        return _canonical_json(_ledger_payload(ledger))
    except CanonicalSerializationError:
        raise
    except Exception:
        raise CanonicalSerializationError from None


def verification_json(result: HypothesisVerificationResult) -> str:
    """Serialize one deterministic hypothesis-verification result canonically."""
    try:
        return _canonical_json(_verification_payload(result))
    except CanonicalSerializationError:
        raise
    except Exception:
        raise CanonicalSerializationError from None


def metric_evidence_entry_json(entry: MetricShiftEvidence) -> str:
    """Serialize one validated metric-shift evidence entry canonically.

    Additive to the ledger serializer: lets a single content-addressed evidence entry be
    persisted and replayed independently, keyed by its own ``evidence_id``.
    """
    try:
        return _canonical_json(_entry_payload(entry))
    except CanonicalSerializationError:
        raise
    except Exception:
        raise CanonicalSerializationError from None


def _change_event_key(value: object) -> str:
    key = _exact(value, ChangeEventKey)
    return _text(key.value)


def _change_entry_payload(value: object) -> dict[str, object]:
    entry = _exact(value, ChangeEventEvidence)
    return {
        "event_key": _change_event_key(entry.event_key),
        "evidence_id": _evidence_id(entry.evidence_id),
        "kind": _enum_value(entry.kind, ChangeKind),
        "occurred_at": _timestamp(entry.occurred_at),
        "phase": _enum_value(entry.phase, ChangePhase),
    }


def _change_entries_payload(value: object) -> list[dict[str, object]]:
    entries = _exact(value, tuple)
    serialized = [_change_entry_payload(entry) for entry in entries]
    order = [
        (
            cast(str, entry["occurred_at"]),
            cast(str, entry["kind"]),
            cast(str, entry["event_key"]),
        )
        for entry in serialized
    ]
    if order != sorted(order) or len(set(order)) != len(order):
        _fail()
    return serialized


def _change_ledger_payload(value: object) -> dict[str, object]:
    try:
        ledger = validate_change_event_ledger(value)
    except InvalidChangeEventLedgerError:
        _fail()
    schema_version = _text(ledger.schema_version)
    if schema_version != CHANGE_LEDGER_SCHEMA_VERSION:
        _fail()
    return {
        "entries": _change_entries_payload(ledger.entries),
        "incident_id": _identifier(ledger.incident_id, IncidentId),
        "incident_window": _window_payload(ledger.window),
        "run_id": _identifier(ledger.run_id, RunId),
        "schema_version": schema_version,
        "tenant_id": _identifier(ledger.tenant_id, TenantId),
    }


def _change_optional_reason(value: object) -> str | None:
    if value is None:
        return None
    return _enum_value(value, ChangeUnknownReason)


def _change_predicate_result_payload(value: object) -> dict[str, object]:
    result = _exact(value, ChangePredicateVerificationResult)
    verdict = _enum_value(result.verdict, VerificationVerdict)
    reason = _change_optional_reason(result.reason)
    phase_constraint = _enum_value(result.phase_constraint, ChangePhaseConstraint)
    supporting = _evidence_ids(result.supporting_evidence_ids)
    contradicting = _evidence_ids(result.contradicting_evidence_ids)
    if set(supporting) & set(contradicting):
        _fail()
    if verdict == VerificationVerdict.UNKNOWN.value:
        if reason is None or supporting or contradicting:
            _fail()
    elif reason is not None:
        _fail()
    elif verdict == VerificationVerdict.SUPPORTED.value:
        if not supporting or contradicting:
            _fail()
    elif verdict == VerificationVerdict.REFUTED.value:
        if supporting or not contradicting:
            _fail()
    else:
        _fail()
    return {
        "contradicting_evidence_ids": contradicting,
        "phase_constraint": phase_constraint,
        "predicate_id": _text(result.predicate_id),
        "reason": reason,
        "supporting_evidence_ids": supporting,
        "verdict": verdict,
    }


def _change_predicate_results(value: object) -> list[dict[str, object]]:
    results = _exact(value, tuple)
    serialized = [_change_predicate_result_payload(result) for result in results]
    predicate_ids = [cast(str, result["predicate_id"]) for result in serialized]
    if len(set(predicate_ids)) != len(predicate_ids):
        _fail()
    return serialized


def _change_verification_payload(value: object) -> dict[str, object]:
    result = _exact(value, ChangeHypothesisVerificationResult)
    composition = _enum_value(result.composition, HypothesisComposition)
    verdict = _enum_value(result.verdict, VerificationVerdict)
    reason = _change_optional_reason(result.reason)
    predicates = _change_predicate_results(result.predicate_results)
    if not predicates:
        _fail()
    supporting = _evidence_ids(result.supporting_evidence_ids)
    contradicting = _evidence_ids(result.contradicting_evidence_ids)
    expected_supporting = [
        evidence_id
        for predicate in predicates
        for evidence_id in cast(list[str], predicate["supporting_evidence_ids"])
    ]
    expected_contradicting = [
        evidence_id
        for predicate in predicates
        for evidence_id in cast(list[str], predicate["contradicting_evidence_ids"])
    ]
    if supporting != expected_supporting or contradicting != expected_contradicting:
        _fail()

    child_verdicts = tuple(cast(str, predicate["verdict"]) for predicate in predicates)
    if composition == HypothesisComposition.ALL.value:
        expected_verdict = (
            VerificationVerdict.REFUTED.value
            if VerificationVerdict.REFUTED.value in child_verdicts
            else VerificationVerdict.UNKNOWN.value
            if VerificationVerdict.UNKNOWN.value in child_verdicts
            else VerificationVerdict.SUPPORTED.value
        )
    else:
        expected_verdict = (
            VerificationVerdict.SUPPORTED.value
            if VerificationVerdict.SUPPORTED.value in child_verdicts
            else VerificationVerdict.UNKNOWN.value
            if VerificationVerdict.UNKNOWN.value in child_verdicts
            else VerificationVerdict.REFUTED.value
        )
    if verdict != expected_verdict:
        _fail()

    gate_reasons = {
        ChangeUnknownReason.CONTEXT_MISMATCH.value,
        ChangeUnknownReason.CAUSAL_CLAIM_NOT_VERIFIABLE.value,
    }
    if reason is not None:
        if reason not in gate_reasons or verdict != VerificationVerdict.UNKNOWN.value:
            _fail()
        if supporting or contradicting:
            _fail()
        if any(
            predicate["verdict"] != VerificationVerdict.UNKNOWN.value
            or predicate["reason"] != reason
            or predicate["supporting_evidence_ids"]
            or predicate["contradicting_evidence_ids"]
            for predicate in predicates
        ):
            _fail()
    elif any(predicate["reason"] in gate_reasons for predicate in predicates):
        _fail()

    return {
        "composition": composition,
        "contradicting_evidence_ids": contradicting,
        "hypothesis_id": _text(result.hypothesis_id),
        "predicate_results": predicates,
        "reason": reason,
        "schema_version": CHANGE_VERIFICATION_SCHEMA_VERSION,
        "supporting_evidence_ids": supporting,
        "verdict": verdict,
    }


def change_ledger_json(ledger: ChangeEventLedger) -> str:
    """Serialize one validated change-event ledger canonically."""
    try:
        return _canonical_json(_change_ledger_payload(ledger))
    except CanonicalSerializationError:
        raise
    except Exception:
        raise CanonicalSerializationError from None


def change_verification_json(result: ChangeHypothesisVerificationResult) -> str:
    """Serialize one deterministic change-verification result canonically."""
    try:
        return _canonical_json(_change_verification_payload(result))
    except CanonicalSerializationError:
        raise
    except Exception:
        raise CanonicalSerializationError from None


__all__ = [
    "CHANGE_VERIFICATION_SCHEMA_VERSION",
    "VERIFICATION_SCHEMA_VERSION",
    "CanonicalSerializationError",
    "change_ledger_json",
    "change_verification_json",
    "ledger_json",
    "verification_json",
]
