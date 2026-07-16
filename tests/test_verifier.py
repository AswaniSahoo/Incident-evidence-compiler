from __future__ import annotations

import itertools
import math
import unittest
from collections.abc import Iterable
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

from incident_evidence_compiler.domain.baseline import (
    BaselinePolicy,
    SignalBaselineInput,
    rank_metric_shifts,
)
from incident_evidence_compiler.domain.errors import (
    InvalidEvidenceLedgerError,
    InvalidHypothesisError,
)
from incident_evidence_compiler.domain.evidence import (
    MetricEvidenceLedger,
    compile_metric_shift_ledger,
)
from incident_evidence_compiler.domain.hypotheses import (
    ExpectedDirection,
    HypothesisComposition,
    HypothesisDocument,
    HypothesisSemantics,
    MetricShiftPredicate,
)
from incident_evidence_compiler.domain.identifiers import EvidenceId, IncidentId, RunId, TenantId
from incident_evidence_compiler.domain.incidents import IncidentWindow
from incident_evidence_compiler.domain.metrics import MetricPoint, MetricSignal, SignalKey
from incident_evidence_compiler.domain.verifier import (
    ObservedDirection,
    UnknownReason,
    VerificationVerdict,
    verify_hypothesis,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)
TENANT = TenantId("tenant-canary")
INCIDENT = IncidentId("incident-canary")
RUN = RunId("run-canary")


def window() -> IncidentWindow:
    return IncidentWindow(BASE, BASE + timedelta(minutes=10), BASE + timedelta(minutes=20))


def baseline_input(
    name: str,
    pre: tuple[float, ...],
    post: tuple[float, ...],
) -> SignalBaselineInput:
    points = tuple(
        MetricPoint(BASE + timedelta(minutes=index), value) for index, value in enumerate(pre)
    ) + tuple(
        MetricPoint(BASE + timedelta(minutes=10 + index), value) for index, value in enumerate(post)
    )
    return SignalBaselineInput(MetricSignal(SignalKey(name), points), 1.0)


def ledger_for(
    inputs: tuple[SignalBaselineInput, ...],
    *,
    minimum_points: int = 2,
    minimum_score: float = 1.0,
    minimum_margin: float = 0.0,
) -> MetricEvidenceLedger:
    policy = BaselinePolicy(minimum_points, minimum_score, minimum_margin, 0.0)
    result = rank_metric_shifts(window(), inputs, policy)
    return compile_metric_shift_ledger(TENANT, INCIDENT, RUN, window(), result)


def predicate(
    predicate_id: str,
    signal: str,
    direction: ExpectedDirection = ExpectedDirection.INCREASE,
) -> MetricShiftPredicate:
    return MetricShiftPredicate(predicate_id, SignalKey(signal), direction)


def hypothesis(
    predicates: Iterable[MetricShiftPredicate],
    *,
    tenant_id: TenantId = TENANT,
    incident_id: IncidentId = INCIDENT,
    run_id: RunId = RUN,
    semantics: HypothesisSemantics = HypothesisSemantics.DESCRIPTIVE,
    composition: HypothesisComposition = HypothesisComposition.ALL,
) -> HypothesisDocument:
    return HypothesisDocument(
        "hypothesis-canary",
        tenant_id,
        incident_id,
        run_id,
        semantics,
        composition,
        predicates,
    )


class HypothesisContractTests(unittest.TestCase):
    def test_document_materializes_once_and_is_deeply_immutable(self) -> None:
        source = [predicate("p1", "cpu")]
        document = hypothesis(iter(source))
        source.append(predicate("p2", "memory"))
        self.assertEqual(len(document.predicates), 1)
        self.assertIsInstance(document.predicates, tuple)
        with self.assertRaises(FrozenInstanceError):
            document.hypothesis_id = "changed"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            document.predicates[0].predicate_id = "changed"  # type: ignore[misc]

    def test_rejects_invalid_types_empty_and_excess_predicates(self) -> None:
        invalid_predicate_args: tuple[tuple[object, object, object], ...] = (
            ("", SignalKey("cpu"), ExpectedDirection.INCREASE),
            ("p", "cpu", ExpectedDirection.INCREASE),
            ("p", SignalKey("cpu"), "increase"),
        )
        for args in invalid_predicate_args:
            with self.subTest(args=tuple(type(value).__name__ for value in args)):
                with self.assertRaises(InvalidHypothesisError):
                    MetricShiftPredicate(*args)  # type: ignore[arg-type]

        with self.assertRaises(InvalidHypothesisError):
            hypothesis(())
        too_many = tuple(predicate(f"p{index}", f"s{index}") for index in range(33))
        with self.assertRaises(InvalidHypothesisError):
            hypothesis(too_many)
        with self.assertRaises(InvalidHypothesisError):
            HypothesisDocument(
                "h",
                TENANT,
                INCIDENT,
                RUN,
                "descriptive",  # type: ignore[arg-type]
                HypothesisComposition.ALL,
                (predicate("p", "cpu"),),
            )

        def hostile() -> Iterable[MetricShiftPredicate]:
            yield predicate("p", "cpu")
            raise RuntimeError("ITERATOR_SECRET")

        with self.assertRaises(InvalidHypothesisError) as caught:
            hypothesis(hostile())
        self.assertEqual(str(caught.exception), "invalid_hypothesis")
        self.assertNotIn("ITERATOR_SECRET", str(caught.exception))

    def test_rejects_duplicate_predicate_ids_and_signal_keys(self) -> None:
        with self.assertRaises(InvalidHypothesisError):
            hypothesis((predicate("same", "cpu"), predicate("same", "memory")))
        with self.assertRaises(InvalidHypothesisError):
            hypothesis(
                (
                    predicate("increase", "cpu", ExpectedDirection.INCREASE),
                    predicate("decrease", "cpu", ExpectedDirection.DECREASE),
                )
            )

    def test_repr_is_bounded_and_does_not_expose_identifiers_or_signals(self) -> None:
        document = hypothesis((predicate("PREDICATE_SECRET", "SIGNAL_SECRET"),))
        text = repr(document) + repr(document.predicates[0])
        for canary in (
            "PREDICATE_SECRET",
            "SIGNAL_SECRET",
            TENANT.value,
            INCIDENT.value,
            RUN.value,
        ):
            self.assertNotIn(canary, text)
        self.assertIn("predicate_count=1", text)


class VerificationPrecedenceTests(unittest.TestCase):
    def test_context_precedes_causal_and_suppresses_observations(self) -> None:
        ledger = ledger_for((baseline_input("cpu", (0, 0), (3, 3)),))
        document = hypothesis(
            (predicate("p", "cpu"),),
            tenant_id=TenantId("foreign"),
            semantics=HypothesisSemantics.CAUSAL,
        )
        result = verify_hypothesis(document, ledger)
        self.assertEqual(result.verdict, VerificationVerdict.UNKNOWN)
        self.assertEqual(result.reason, UnknownReason.CONTEXT_MISMATCH)
        child = result.predicate_results[0]
        self.assertEqual(child.reason, UnknownReason.CONTEXT_MISMATCH)
        self.assertIsNone(child.observed_direction)
        self.assertEqual(child.supporting_evidence_ids, ())
        self.assertEqual(child.contradicting_evidence_ids, ())
        self.assertEqual(result.supporting_evidence_ids, ())
        self.assertEqual(result.contradicting_evidence_ids, ())

    def test_each_context_binding_is_exact(self) -> None:
        ledger = ledger_for((baseline_input("cpu", (0, 0), (3, 3)),))
        variants = (
            {"tenant_id": TenantId("foreign")},
            {"incident_id": IncidentId("foreign")},
            {"run_id": RunId("foreign")},
        )
        for override in variants:
            with self.subTest(field=next(iter(override))):
                result = verify_hypothesis(
                    hypothesis((predicate("p", "cpu"),), **override),
                    ledger,
                )
                self.assertEqual(result.reason, UnknownReason.CONTEXT_MISMATCH)

    def test_causal_gate_precedes_signal_lookup_and_exposes_no_evidence(self) -> None:
        ledger = ledger_for((baseline_input("cpu", (0, 0), (3, 3)),))
        result = verify_hypothesis(
            hypothesis(
                (predicate("p", "missing"),),
                semantics=HypothesisSemantics.CAUSAL,
            ),
            ledger,
        )
        self.assertEqual(result.reason, UnknownReason.CAUSAL_CLAIM_NOT_VERIFIABLE)
        self.assertEqual(
            result.predicate_results[0].reason,
            UnknownReason.CAUSAL_CLAIM_NOT_VERIFIABLE,
        )
        self.assertIsNone(result.predicate_results[0].observed_direction)
        self.assertEqual(result.supporting_evidence_ids, ())
        self.assertEqual(result.contradicting_evidence_ids, ())

    def test_missing_ineligible_zero_and_weak_have_exact_precedence(self) -> None:
        cases = (
            (
                ledger_for((baseline_input("other", (0, 0), (3, 3)),)),
                "missing",
                UnknownReason.SIGNAL_NOT_FOUND,
                None,
            ),
            (
                ledger_for(
                    (baseline_input("short", (0,), (3, 3)),),
                    minimum_points=2,
                ),
                "short",
                UnknownReason.INSUFFICIENT_EVIDENCE,
                None,
            ),
            (
                ledger_for(
                    (baseline_input("zero", (1, 1), (1, 1)),),
                    minimum_score=0.0,
                ),
                "zero",
                UnknownReason.NO_DIRECTIONAL_SHIFT,
                None,
            ),
            (
                ledger_for(
                    (baseline_input("weak", (0, 0), (1, 1)),),
                    minimum_score=2.0,
                ),
                "weak",
                UnknownReason.WEAK_EVIDENCE,
                ObservedDirection.INCREASE,
            ),
        )
        for ledger, signal, reason, observed in cases:
            with self.subTest(reason=reason):
                result = verify_hypothesis(hypothesis((predicate("p", signal),)), ledger)
                child = result.predicate_results[0]
                self.assertEqual(result.verdict, VerificationVerdict.UNKNOWN)
                self.assertEqual(child.reason, reason)
                self.assertEqual(child.observed_direction, observed)
                self.assertEqual(child.supporting_evidence_ids, ())
                self.assertEqual(child.contradicting_evidence_ids, ())


class VerificationSignAndThresholdTests(unittest.TestCase):
    def test_inclusive_threshold_and_both_signs_support_or_refute(self) -> None:
        cases = (
            ("up", (0.0, 0.0), (2.0, 2.0), ExpectedDirection.INCREASE, True),
            ("up", (0.0, 0.0), (2.0, 2.0), ExpectedDirection.DECREASE, False),
            ("down", (2.0, 2.0), (0.0, 0.0), ExpectedDirection.DECREASE, True),
            ("down", (2.0, 2.0), (0.0, 0.0), ExpectedDirection.INCREASE, False),
        )
        for name, pre, post, expected, supported in cases:
            with self.subTest(name=name, expected=expected):
                ledger = ledger_for(
                    (baseline_input(name, pre, post),),
                    minimum_score=2.0,
                )
                result = verify_hypothesis(
                    hypothesis((predicate("p", name, expected),)),
                    ledger,
                )
                child = result.predicate_results[0]
                expected_verdict = (
                    VerificationVerdict.SUPPORTED if supported else VerificationVerdict.REFUTED
                )
                self.assertEqual(child.verdict, expected_verdict)
                self.assertEqual(child.minimum_score, 2.0)
                self.assertEqual(child.threshold, 2.0)
                self.assertIsNone(child.reason)
                if supported:
                    self.assertEqual(len(child.supporting_evidence_ids), 1)
                    self.assertEqual(child.contradicting_evidence_ids, ())
                else:
                    self.assertEqual(child.supporting_evidence_ids, ())
                    self.assertEqual(len(child.contradicting_evidence_ids), 1)

    def test_global_baseline_margin_does_not_govern_signal_predicate(self) -> None:
        ledger = ledger_for(
            (
                baseline_input("a", (0, 0), (3, 3)),
                baseline_input("b", (0, 0), (3, 3)),
            ),
            minimum_score=1.0,
            minimum_margin=100.0,
        )
        abstention_reason = ledger.decision.abstention_reason
        self.assertIsNotNone(abstention_reason)
        assert abstention_reason is not None
        self.assertEqual(abstention_reason.value, "ambiguous_evidence")
        result = verify_hypothesis(hypothesis((predicate("p", "a"),)), ledger)
        self.assertEqual(result.verdict, VerificationVerdict.SUPPORTED)
        self.assertEqual(result.predicate_results[0].verdict, VerificationVerdict.SUPPORTED)


class ThreeValuedCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = ledger_for(
            (
                baseline_input("s1", (0, 0), (2, 2)),
                baseline_input("s2", (0, 0), (2, 2)),
                baseline_input("s3", (0, 0), (2, 2)),
            ),
            minimum_score=1.0,
        )

    def make_predicate(self, verdict: VerificationVerdict, index: int) -> MetricShiftPredicate:
        if verdict is VerificationVerdict.UNKNOWN:
            return predicate(f"p{index}", f"missing{index}")
        direction = (
            ExpectedDirection.INCREASE
            if verdict is VerificationVerdict.SUPPORTED
            else ExpectedDirection.DECREASE
        )
        return predicate(f"p{index}", f"s{index + 1}", direction)

    def test_complete_all_and_any_truth_tables_and_permutations(self) -> None:
        verdicts = tuple(VerificationVerdict)
        for left, right in itertools.product(verdicts, repeat=2):
            for composition in HypothesisComposition:
                expected = (
                    (
                        VerificationVerdict.REFUTED
                        if VerificationVerdict.REFUTED in (left, right)
                        else VerificationVerdict.UNKNOWN
                        if VerificationVerdict.UNKNOWN in (left, right)
                        else VerificationVerdict.SUPPORTED
                    )
                    if composition is HypothesisComposition.ALL
                    else (
                        VerificationVerdict.SUPPORTED
                        if VerificationVerdict.SUPPORTED in (left, right)
                        else VerificationVerdict.UNKNOWN
                        if VerificationVerdict.UNKNOWN in (left, right)
                        else VerificationVerdict.REFUTED
                    )
                )
                for ordered in ((left, right), (right, left)):
                    with self.subTest(
                        left=left,
                        right=right,
                        composition=composition,
                        ordered=ordered,
                    ):
                        predicates = tuple(
                            self.make_predicate(verdict, index)
                            for index, verdict in enumerate(ordered)
                        )
                        result = verify_hypothesis(
                            hypothesis(predicates, composition=composition),
                            self.ledger,
                        )
                        self.assertEqual(result.verdict, expected)
                        self.assertEqual(len(result.predicate_results), 2)
                        self.assertEqual(
                            tuple(item.predicate_id for item in result.predicate_results),
                            ("p0", "p1"),
                        )
                        self.assertEqual(
                            tuple(item.verdict for item in result.predicate_results),
                            ordered,
                        )

    def test_decisive_composition_retains_unknown_trace(self) -> None:
        all_result = verify_hypothesis(
            hypothesis(
                (
                    predicate("unknown", "missing"),
                    predicate("refuted", "s2", ExpectedDirection.DECREASE),
                ),
                composition=HypothesisComposition.ALL,
            ),
            self.ledger,
        )
        self.assertEqual(all_result.verdict, VerificationVerdict.REFUTED)
        self.assertEqual(all_result.predicate_results[0].reason, UnknownReason.SIGNAL_NOT_FOUND)
        self.assertEqual(len(all_result.predicate_results), 2)

        any_result = verify_hypothesis(
            hypothesis(
                (
                    predicate("unknown", "missing"),
                    predicate("supported", "s2", ExpectedDirection.INCREASE),
                ),
                composition=HypothesisComposition.ANY,
            ),
            self.ledger,
        )
        self.assertEqual(any_result.verdict, VerificationVerdict.SUPPORTED)
        self.assertEqual(any_result.predicate_results[0].reason, UnknownReason.SIGNAL_NOT_FOUND)
        self.assertEqual(len(any_result.predicate_results), 2)


class AdversarialBoundaryTests(unittest.TestCase):
    def test_forged_nonfinite_ledger_is_rejected_with_sanitized_error(self) -> None:
        ledger = ledger_for((baseline_input("SIGNAL_SECRET", (0, 0), (2, 2)),))
        candidate = ledger.entries[0].candidate
        assert candidate is not None
        forged_entry = replace(
            ledger.entries[0],
            candidate=replace(candidate, signed_score=math.nan),
        )
        forged = replace(ledger, entries=(forged_entry,))
        with self.assertRaises(InvalidEvidenceLedgerError) as caught:
            verify_hypothesis(hypothesis((predicate("p", "SIGNAL_SECRET"),)), forged)
        self.assertEqual(str(caught.exception), "invalid_evidence_ledger")
        self.assertNotIn("SIGNAL_SECRET", str(caught.exception))

    def test_invalid_hypothesis_type_is_rejected_with_sanitized_error(self) -> None:
        ledger = ledger_for((baseline_input("cpu", (0, 0), (2, 2)),))
        with self.assertRaises(InvalidHypothesisError) as caught:
            verify_hypothesis(object(), ledger)  # type: ignore[arg-type]
        self.assertEqual(str(caught.exception), "invalid_hypothesis")

    def test_result_repr_exposes_only_verdict_and_counts(self) -> None:
        ledger = ledger_for((baseline_input("SIGNAL_SECRET", (0, 0), (2, 2)),))
        result = verify_hypothesis(
            hypothesis((predicate("PREDICATE_SECRET", "SIGNAL_SECRET"),)),
            ledger,
        )
        text = repr(result) + repr(result.predicate_results[0])
        for canary in (
            "SIGNAL_SECRET",
            "PREDICATE_SECRET",
            TENANT.value,
            INCIDENT.value,
            RUN.value,
            ledger.entries[0].evidence_id.value,
        ):
            self.assertNotIn(canary, text)
        self.assertIn("predicate_count=1", text)
        self.assertIn("verdict='supported'", text)


class ReconstructionBoundaryTests(unittest.TestCase):
    def test_construction_deeply_copies_predicates_and_nested_signal_keys(self) -> None:
        source_predicate = predicate("p", "cpu")
        document = hypothesis((source_predicate,))
        object.__setattr__(source_predicate.signal_key, "value", "mutated")
        object.__setattr__(source_predicate, "predicate_id", "mutated")
        self.assertEqual(document.predicates[0].predicate_id, "p")
        self.assertEqual(document.predicates[0].signal_key.value, "cpu")
        self.assertIsNot(document.predicates[0], source_predicate)
        self.assertIsNot(document.predicates[0].signal_key, source_predicate.signal_key)

    def test_verifier_revalidates_deeply_mutated_hypothesis(self) -> None:
        ledger = ledger_for((baseline_input("cpu", (0, 0), (2, 2)),))
        document = hypothesis((predicate("p", "cpu"),))
        object.__setattr__(document.predicates[0], "expected_direction", "increase")
        with self.assertRaises(InvalidHypothesisError) as caught:
            verify_hypothesis(document, ledger)
        self.assertEqual(str(caught.exception), "invalid_hypothesis")

    def test_verifier_rejects_forged_semantics_and_composition_enums(self) -> None:
        ledger = ledger_for((baseline_input("cpu", (0, 0), (2, 2)),))
        for field, forged_value in (
            ("semantics", "causal"),
            ("composition", "all"),
        ):
            with self.subTest(field=field):
                document = hypothesis((predicate("p", "cpu"),))
                object.__setattr__(document, field, forged_value)
                with self.assertRaises(InvalidHypothesisError):
                    verify_hypothesis(document, ledger)

    def test_verifier_rejects_stale_content_bound_evidence_id(self) -> None:
        ledger = ledger_for((baseline_input("cpu", (0, 0), (2, 2)),))
        stale_entry = replace(ledger.entries[0], evidence_id=EvidenceId("sha256:" + "0" * 64))
        with self.assertRaises(InvalidEvidenceLedgerError):
            verify_hypothesis(
                hypothesis((predicate("p", "cpu"),)),
                replace(ledger, entries=(stale_entry,)),
            )


if __name__ == "__main__":
    unittest.main()
