"""Deterministic tri-state verification of change co-occurrence hypotheses.

The verifier answers only a descriptive question: did a change of an exact kind
to an exact target occur in the asserted temporal region of this run's incident
window? It never asserts that a change caused a metric shift or an incident. It
reuses the Phase 2 verdict enum and three-valued composition, and keeps a
distinct reason vocabulary so the frozen metric verifier is untouched.
"""

from dataclasses import dataclass
from enum import StrEnum

from .change_evidence import (
    ChangeEventEvidence,
    ChangeEventLedger,
    ChangePhase,
    validate_change_event_ledger,
)
from .change_hypotheses import (
    ChangeCooccurrencePredicate,
    ChangeHypothesisDocument,
    ChangePhaseConstraint,
    validate_change_hypothesis_document,
)
from .hypotheses import HypothesisComposition, HypothesisSemantics
from .identifiers import EvidenceId
from .verifier import VerificationVerdict


class ChangeUnknownReason(StrEnum):
    """Stable reasons why change evidence cannot decide a co-occurrence claim."""

    CONTEXT_MISMATCH = "context_mismatch"
    CAUSAL_CLAIM_NOT_VERIFIABLE = "causal_claim_not_verifiable"
    CHANGE_NOT_OBSERVED = "change_not_observed"


@dataclass(frozen=True, slots=True, repr=False)
class ChangePredicateVerificationResult:
    """A complete, leakage-aware trace for one declared co-occurrence predicate."""

    predicate_id: str
    verdict: VerificationVerdict
    reason: ChangeUnknownReason | None
    phase_constraint: ChangePhaseConstraint
    supporting_evidence_ids: tuple[EvidenceId, ...]
    contradicting_evidence_ids: tuple[EvidenceId, ...]

    def __repr__(self) -> str:
        return f"ChangePredicateVerificationResult(verdict='{self.verdict.value}')"


@dataclass(frozen=True, slots=True, repr=False)
class ChangeHypothesisVerificationResult:
    """The composed verdict plus every child trace in declaration order."""

    hypothesis_id: str
    composition: HypothesisComposition
    verdict: VerificationVerdict
    reason: ChangeUnknownReason | None
    predicate_results: tuple[ChangePredicateVerificationResult, ...]
    supporting_evidence_ids: tuple[EvidenceId, ...]
    contradicting_evidence_ids: tuple[EvidenceId, ...]

    @property
    def results(self) -> tuple[ChangePredicateVerificationResult, ...]:
        """Concise alias for callers rendering the complete predicate trace."""
        return self.predicate_results

    def __repr__(self) -> str:
        return (
            f"ChangeHypothesisVerificationResult(verdict='{self.verdict.value}', "
            f"predicate_count={len(self.predicate_results)})"
        )


def _phase_satisfies(phase: ChangePhase, constraint: ChangePhaseConstraint) -> bool:
    if constraint is ChangePhaseConstraint.WITHIN_WINDOW:
        return phase is ChangePhase.PRE_INJECTION or phase is ChangePhase.POST_INJECTION
    if constraint is ChangePhaseConstraint.PRE_INJECTION:
        return phase is ChangePhase.PRE_INJECTION
    return phase is ChangePhase.POST_INJECTION


def _unknown(
    predicate: ChangeCooccurrencePredicate,
    reason: ChangeUnknownReason,
) -> ChangePredicateVerificationResult:
    return ChangePredicateVerificationResult(
        predicate_id=predicate.predicate_id,
        verdict=VerificationVerdict.UNKNOWN,
        reason=reason,
        phase_constraint=predicate.phase_constraint,
        supporting_evidence_ids=(),
        contradicting_evidence_ids=(),
    )


def _evaluate_predicate(
    predicate: ChangeCooccurrencePredicate,
    entries: tuple[ChangeEventEvidence, ...],
) -> ChangePredicateVerificationResult:
    matching = tuple(
        entry
        for entry in entries
        if entry.event_key == predicate.event_key and entry.kind is predicate.kind
    )
    if not matching:
        # Absence of a change record is not proof the change did not happen.
        return _unknown(predicate, ChangeUnknownReason.CHANGE_NOT_OBSERVED)

    supporting = tuple(
        entry.evidence_id
        for entry in matching
        if _phase_satisfies(entry.phase, predicate.phase_constraint)
    )
    if supporting:
        return ChangePredicateVerificationResult(
            predicate_id=predicate.predicate_id,
            verdict=VerificationVerdict.SUPPORTED,
            reason=None,
            phase_constraint=predicate.phase_constraint,
            supporting_evidence_ids=supporting,
            contradicting_evidence_ids=(),
        )
    # The change is recorded, but only at times incompatible with the assertion.
    return ChangePredicateVerificationResult(
        predicate_id=predicate.predicate_id,
        verdict=VerificationVerdict.REFUTED,
        reason=None,
        phase_constraint=predicate.phase_constraint,
        supporting_evidence_ids=(),
        contradicting_evidence_ids=tuple(entry.evidence_id for entry in matching),
    )


def _compose(
    composition: HypothesisComposition,
    results: tuple[ChangePredicateVerificationResult, ...],
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


def verify_change_hypothesis(
    hypothesis: ChangeHypothesisDocument,
    ledger: ChangeEventLedger,
) -> ChangeHypothesisVerificationResult:
    """Verify every predicate in order, then compose their three-valued verdicts."""
    validated_hypothesis = validate_change_hypothesis_document(hypothesis)
    validated_ledger = validate_change_event_ledger(ledger)
    entries = validated_ledger.entries
    context_matches = (
        validated_hypothesis.tenant_id == validated_ledger.tenant_id
        and validated_hypothesis.incident_id == validated_ledger.incident_id
        and validated_hypothesis.run_id == validated_ledger.run_id
    )

    document_reason: ChangeUnknownReason | None = None
    if not context_matches:
        document_reason = ChangeUnknownReason.CONTEXT_MISMATCH
        results = tuple(
            _unknown(predicate, document_reason) for predicate in validated_hypothesis.predicates
        )
        verdict = VerificationVerdict.UNKNOWN
    elif validated_hypothesis.semantics is HypothesisSemantics.CAUSAL:
        document_reason = ChangeUnknownReason.CAUSAL_CLAIM_NOT_VERIFIABLE
        results = tuple(
            _unknown(predicate, document_reason) for predicate in validated_hypothesis.predicates
        )
        verdict = VerificationVerdict.UNKNOWN
    else:
        results = tuple(
            _evaluate_predicate(predicate, entries) for predicate in validated_hypothesis.predicates
        )
        verdict = _compose(validated_hypothesis.composition, results)

    supporting = tuple(
        evidence_id for result in results for evidence_id in result.supporting_evidence_ids
    )
    contradicting = tuple(
        evidence_id for result in results for evidence_id in result.contradicting_evidence_ids
    )
    return ChangeHypothesisVerificationResult(
        hypothesis_id=validated_hypothesis.hypothesis_id,
        composition=validated_hypothesis.composition,
        verdict=verdict,
        reason=document_reason,
        predicate_results=results,
        supporting_evidence_ids=supporting,
        contradicting_evidence_ids=contradicting,
    )
