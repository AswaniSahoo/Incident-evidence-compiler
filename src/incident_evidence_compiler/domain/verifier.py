"""Deterministic tri-state verification of restricted metric hypotheses."""

from dataclasses import dataclass
from enum import StrEnum

from .evidence import (
    MetricEvidenceLedger,
    MetricShiftEvidence,
    validate_metric_evidence_ledger,
)
from .hypotheses import (
    HypothesisComposition,
    HypothesisDocument,
    HypothesisSemantics,
    MetricShiftPredicate,
    validate_hypothesis_document,
)
from .identifiers import EvidenceId


class VerificationVerdict(StrEnum):
    """The only public outcomes of deterministic verification."""

    SUPPORTED = "supported"
    REFUTED = "refuted"
    UNKNOWN = "unknown"


class UnknownReason(StrEnum):
    """Stable reasons why available metric evidence cannot decide a predicate."""

    CONTEXT_MISMATCH = "context_mismatch"
    CAUSAL_CLAIM_NOT_VERIFIABLE = "causal_claim_not_verifiable"
    SIGNAL_NOT_FOUND = "signal_not_found"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NO_DIRECTIONAL_SHIFT = "no_directional_shift"
    WEAK_EVIDENCE = "weak_evidence"


# A descriptive alias keeps the reason type discoverable without creating another enum.
VerificationReason = UnknownReason


class ObservedDirection(StrEnum):
    """The non-zero sign of an eligible metric-shift score."""

    INCREASE = "increase"
    DECREASE = "decrease"


@dataclass(frozen=True, slots=True, repr=False)
class PredicateVerificationResult:
    """A complete, leakage-aware trace for one declared predicate."""

    predicate_id: str
    verdict: VerificationVerdict
    reason: UnknownReason | None
    observed_direction: ObservedDirection | None
    minimum_score: float
    supporting_evidence_ids: tuple[EvidenceId, ...]
    contradicting_evidence_ids: tuple[EvidenceId, ...]

    @property
    def threshold(self) -> float:
        """Alias for the frozen policy threshold used by the verifier."""
        return self.minimum_score

    def __repr__(self) -> str:
        return f"PredicateVerificationResult(verdict='{self.verdict.value}')"


@dataclass(frozen=True, slots=True, repr=False)
class HypothesisVerificationResult:
    """The composed verdict plus every child trace in declaration order."""

    hypothesis_id: str
    composition: HypothesisComposition
    verdict: VerificationVerdict
    reason: UnknownReason | None
    predicate_results: tuple[PredicateVerificationResult, ...]
    supporting_evidence_ids: tuple[EvidenceId, ...]
    contradicting_evidence_ids: tuple[EvidenceId, ...]

    @property
    def results(self) -> tuple[PredicateVerificationResult, ...]:
        """Concise alias for callers rendering the complete predicate trace."""
        return self.predicate_results

    def __repr__(self) -> str:
        return (
            f"HypothesisVerificationResult(verdict='{self.verdict.value}', "
            f"predicate_count={len(self.predicate_results)})"
        )


def _unknown(
    predicate: MetricShiftPredicate,
    reason: UnknownReason,
    minimum_score: float,
    *,
    observed_direction: ObservedDirection | None = None,
) -> PredicateVerificationResult:
    return PredicateVerificationResult(
        predicate_id=predicate.predicate_id,
        verdict=VerificationVerdict.UNKNOWN,
        reason=reason,
        observed_direction=observed_direction,
        minimum_score=minimum_score,
        supporting_evidence_ids=(),
        contradicting_evidence_ids=(),
    )


def _evaluate_predicate(
    predicate: MetricShiftPredicate,
    entry: MetricShiftEvidence | None,
    minimum_score: float,
) -> PredicateVerificationResult:
    if entry is None:
        return _unknown(predicate, UnknownReason.SIGNAL_NOT_FOUND, minimum_score)
    if not entry.eligible or entry.candidate is None:
        return _unknown(predicate, UnknownReason.INSUFFICIENT_EVIDENCE, minimum_score)

    candidate = entry.candidate
    if candidate.signed_score == 0.0:
        return _unknown(predicate, UnknownReason.NO_DIRECTIONAL_SHIFT, minimum_score)
    observed = (
        ObservedDirection.INCREASE if candidate.signed_score > 0.0 else ObservedDirection.DECREASE
    )
    if candidate.suspicion_score < minimum_score:
        return _unknown(
            predicate,
            UnknownReason.WEAK_EVIDENCE,
            minimum_score,
            observed_direction=observed,
        )

    matches = observed.value == predicate.expected_direction.value
    return PredicateVerificationResult(
        predicate_id=predicate.predicate_id,
        verdict=(VerificationVerdict.SUPPORTED if matches else VerificationVerdict.REFUTED),
        reason=None,
        observed_direction=observed,
        minimum_score=minimum_score,
        supporting_evidence_ids=((entry.evidence_id,) if matches else ()),
        contradicting_evidence_ids=(() if matches else (entry.evidence_id,)),
    )


def _compose(
    composition: HypothesisComposition,
    results: tuple[PredicateVerificationResult, ...],
) -> VerificationVerdict:
    verdicts = tuple(result.verdict for result in results)
    if composition is HypothesisComposition.ALL:
        if VerificationVerdict.REFUTED in verdicts:
            return VerificationVerdict.REFUTED
        if VerificationVerdict.UNKNOWN in verdicts:
            return VerificationVerdict.UNKNOWN
        return VerificationVerdict.SUPPORTED
    if VerificationVerdict.SUPPORTED in verdicts:
        return VerificationVerdict.SUPPORTED
    if VerificationVerdict.UNKNOWN in verdicts:
        return VerificationVerdict.UNKNOWN
    return VerificationVerdict.REFUTED


def verify_hypothesis(
    hypothesis: HypothesisDocument,
    ledger: MetricEvidenceLedger,
) -> HypothesisVerificationResult:
    """Verify every predicate in order, then compose their three-valued verdicts."""
    validated_hypothesis = validate_hypothesis_document(hypothesis)
    validated_ledger = validate_metric_evidence_ledger(ledger)
    entries = validated_ledger.entries
    minimum_score = validated_ledger.policy.minimum_score
    context_matches = (
        validated_hypothesis.tenant_id == validated_ledger.tenant_id
        and validated_hypothesis.incident_id == validated_ledger.incident_id
        and validated_hypothesis.run_id == validated_ledger.run_id
    )

    document_reason: UnknownReason | None = None
    if not context_matches:
        document_reason = UnknownReason.CONTEXT_MISMATCH
        results = tuple(
            _unknown(predicate, document_reason, minimum_score)
            for predicate in validated_hypothesis.predicates
        )
        verdict = VerificationVerdict.UNKNOWN
    elif validated_hypothesis.semantics is HypothesisSemantics.CAUSAL:
        document_reason = UnknownReason.CAUSAL_CLAIM_NOT_VERIFIABLE
        results = tuple(
            _unknown(predicate, document_reason, minimum_score)
            for predicate in validated_hypothesis.predicates
        )
        verdict = VerificationVerdict.UNKNOWN
    else:
        by_signal = {entry.signal_key: entry for entry in entries}
        results = tuple(
            _evaluate_predicate(predicate, by_signal.get(predicate.signal_key), minimum_score)
            for predicate in validated_hypothesis.predicates
        )
        verdict = _compose(validated_hypothesis.composition, results)

    supporting = tuple(
        evidence_id for result in results for evidence_id in result.supporting_evidence_ids
    )
    contradicting = tuple(
        evidence_id for result in results for evidence_id in result.contradicting_evidence_ids
    )
    return HypothesisVerificationResult(
        hypothesis_id=validated_hypothesis.hypothesis_id,
        composition=validated_hypothesis.composition,
        verdict=verdict,
        reason=document_reason,
        predicate_results=results,
        supporting_evidence_ids=supporting,
        contradicting_evidence_ids=contradicting,
    )
