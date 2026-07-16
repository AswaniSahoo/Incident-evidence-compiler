from __future__ import annotations

import itertools
import unittest
from collections.abc import Iterable
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

from incident_evidence_compiler.domain.change_evidence import (
    ChangeEventLedger,
    compile_change_event_ledger,
)
from incident_evidence_compiler.domain.change_hypotheses import (
    ChangeCooccurrencePredicate,
    ChangeHypothesisDocument,
    ChangePhaseConstraint,
)
from incident_evidence_compiler.domain.change_verifier import (
    ChangeUnknownReason,
    verify_change_hypothesis,
)
from incident_evidence_compiler.domain.changes import (
    ChangeEvent,
    ChangeEventKey,
    ChangeEventLog,
    ChangeKind,
)
from incident_evidence_compiler.domain.errors import InvalidChangeHypothesisError
from incident_evidence_compiler.domain.hypotheses import HypothesisComposition, HypothesisSemantics
from incident_evidence_compiler.domain.identifiers import IncidentId, RunId, TenantId
from incident_evidence_compiler.domain.incidents import IncidentWindow
from incident_evidence_compiler.domain.verifier import VerificationVerdict

BASE = datetime(2026, 1, 1, tzinfo=UTC)
TENANT = TenantId("tenant-01")
INCIDENT = IncidentId("incident-01")
RUN = RunId("run-01")


def window() -> IncidentWindow:
    return IncidentWindow(BASE, BASE + timedelta(minutes=10), BASE + timedelta(minutes=20))


def event(name: str, kind: ChangeKind, minute: float) -> ChangeEvent:
    return ChangeEvent(ChangeEventKey(name), kind, BASE + timedelta(minutes=minute))


def base_ledger() -> ChangeEventLedger:
    return compile_change_event_ledger(
        TENANT,
        INCIDENT,
        RUN,
        window(),
        ChangeEventLog(
            (
                event("svc-pre", ChangeKind.DEPLOYMENT, 5),
                event("svc-pre", ChangeKind.DEPLOYMENT, 7),
                event("svc-post", ChangeKind.ROLLBACK, 15),
                event("svc-early", ChangeKind.CONFIGURATION, -5),
            )
        ),
    )


def hypothesis(
    predicates: Iterable[ChangeCooccurrencePredicate],
    *,
    tenant_id: TenantId = TENANT,
    incident_id: IncidentId = INCIDENT,
    run_id: RunId = RUN,
    semantics: HypothesisSemantics = HypothesisSemantics.DESCRIPTIVE,
    composition: HypothesisComposition = HypothesisComposition.ALL,
) -> ChangeHypothesisDocument:
    return ChangeHypothesisDocument(
        "hypothesis-canary",
        tenant_id,
        incident_id,
        run_id,
        semantics,
        composition,
        predicates,
    )


def supported(predicate_id: str) -> ChangeCooccurrencePredicate:
    return ChangeCooccurrencePredicate(
        predicate_id,
        ChangeEventKey("svc-pre"),
        ChangeKind.DEPLOYMENT,
        ChangePhaseConstraint.PRE_INJECTION,
    )


def refuted(predicate_id: str) -> ChangeCooccurrencePredicate:
    return ChangeCooccurrencePredicate(
        predicate_id,
        ChangeEventKey("svc-pre"),
        ChangeKind.DEPLOYMENT,
        ChangePhaseConstraint.POST_INJECTION,
    )


def unknown(predicate_id: str) -> ChangeCooccurrencePredicate:
    return ChangeCooccurrencePredicate(
        predicate_id,
        ChangeEventKey("svc-absent"),
        ChangeKind.SCALING,
        ChangePhaseConstraint.WITHIN_WINDOW,
    )


BUILDERS = {"S": supported, "R": refuted, "U": unknown}


class ChangeHypothesisContractTests(unittest.TestCase):
    def test_materializes_once_and_is_deeply_immutable(self) -> None:
        source = [supported("p1")]
        document = hypothesis(iter(source))
        source.append(unknown("p2"))
        self.assertEqual(len(document.predicates), 1)
        with self.assertRaises(FrozenInstanceError):
            document.hypothesis_id = "changed"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            document.predicates[0].predicate_id = "changed"  # type: ignore[misc]

    def test_rejects_invalid_predicate_fields(self) -> None:
        invalid: tuple[tuple[object, object, object, object], ...] = (
            ("", ChangeEventKey("svc"), ChangeKind.DEPLOYMENT, ChangePhaseConstraint.WITHIN_WINDOW),
            ("p", "svc", ChangeKind.DEPLOYMENT, ChangePhaseConstraint.WITHIN_WINDOW),
            ("p", ChangeEventKey("svc"), "deployment", ChangePhaseConstraint.WITHIN_WINDOW),
            ("p", ChangeEventKey("svc"), ChangeKind.DEPLOYMENT, "within_window"),
        )
        for args in invalid:
            with self.subTest(args=tuple(type(value).__name__ for value in args)):
                with self.assertRaises(InvalidChangeHypothesisError):
                    ChangeCooccurrencePredicate(*args)  # type: ignore[arg-type]

    def test_rejects_empty_excess_and_duplicate_ids(self) -> None:
        with self.assertRaises(InvalidChangeHypothesisError):
            hypothesis(())
        too_many = tuple(supported(f"p{index}") for index in range(33))
        with self.assertRaises(InvalidChangeHypothesisError):
            hypothesis(too_many)
        with self.assertRaises(InvalidChangeHypothesisError):
            hypothesis((supported("same"), unknown("same")))
        with self.assertRaises(InvalidChangeHypothesisError):
            hypothesis(
                (supported("p"),),
                semantics="descriptive",  # type: ignore[arg-type]
            )

    def test_permits_overlapping_key_kind_with_distinct_ids(self) -> None:
        document = hypothesis((supported("pre"), refuted("post")))
        self.assertEqual(len(document.predicates), 2)

    def test_hostile_iterator_is_contained(self) -> None:
        def hostile() -> Iterable[ChangeCooccurrencePredicate]:
            yield supported("p")
            raise RuntimeError("ITERATOR_SECRET")

        with self.assertRaises(InvalidChangeHypothesisError) as caught:
            hypothesis(hostile())
        self.assertEqual(str(caught.exception), "invalid_change_hypothesis")
        self.assertNotIn("ITERATOR_SECRET", str(caught.exception))

    def test_repr_is_bounded(self) -> None:
        document = hypothesis((supported("PREDICATE_SECRET"),))
        text = repr(document) + repr(document.predicates[0])
        for canary in ("PREDICATE_SECRET", "svc-pre", TENANT.value):
            self.assertNotIn(canary, text)
        self.assertIn("predicate_count=1", text)


class ChangeVerificationPrecedenceTests(unittest.TestCase):
    def test_context_precedes_causal_and_exposes_no_evidence(self) -> None:
        result = verify_change_hypothesis(
            hypothesis(
                (supported("p"),),
                tenant_id=TenantId("foreign"),
                semantics=HypothesisSemantics.CAUSAL,
            ),
            base_ledger(),
        )
        self.assertEqual(result.verdict, VerificationVerdict.UNKNOWN)
        self.assertEqual(result.reason, ChangeUnknownReason.CONTEXT_MISMATCH)
        child = result.predicate_results[0]
        self.assertEqual(child.reason, ChangeUnknownReason.CONTEXT_MISMATCH)
        self.assertEqual(child.supporting_evidence_ids, ())
        self.assertEqual(child.contradicting_evidence_ids, ())
        self.assertEqual(result.supporting_evidence_ids, ())

    def test_each_context_binding_is_exact(self) -> None:
        for override in (
            {"tenant_id": TenantId("foreign")},
            {"incident_id": IncidentId("foreign")},
            {"run_id": RunId("foreign")},
        ):
            with self.subTest(field=next(iter(override))):
                result = verify_change_hypothesis(
                    hypothesis((supported("p"),), **override), base_ledger()
                )
                self.assertEqual(result.reason, ChangeUnknownReason.CONTEXT_MISMATCH)

    def test_causal_gate_exposes_no_evidence(self) -> None:
        result = verify_change_hypothesis(
            hypothesis((supported("p"),), semantics=HypothesisSemantics.CAUSAL),
            base_ledger(),
        )
        self.assertEqual(result.verdict, VerificationVerdict.UNKNOWN)
        self.assertEqual(result.reason, ChangeUnknownReason.CAUSAL_CLAIM_NOT_VERIFIABLE)
        self.assertEqual(result.supporting_evidence_ids, ())


class ChangeCooccurrenceSemanticsTests(unittest.TestCase):
    def test_in_phase_presence_is_supported(self) -> None:
        result = verify_change_hypothesis(hypothesis((supported("p"),)), base_ledger())
        self.assertEqual(result.verdict, VerificationVerdict.SUPPORTED)
        child = result.predicate_results[0]
        self.assertEqual(len(child.supporting_evidence_ids), 2)
        self.assertEqual(child.contradicting_evidence_ids, ())
        self.assertIsNone(child.reason)

    def test_out_of_phase_presence_is_refuted(self) -> None:
        result = verify_change_hypothesis(hypothesis((refuted("p"),)), base_ledger())
        self.assertEqual(result.verdict, VerificationVerdict.REFUTED)
        child = result.predicate_results[0]
        self.assertEqual(child.supporting_evidence_ids, ())
        self.assertEqual(len(child.contradicting_evidence_ids), 2)

    def test_total_absence_is_unknown_not_refuted(self) -> None:
        absent_key = verify_change_hypothesis(hypothesis((unknown("p"),)), base_ledger())
        self.assertEqual(absent_key.verdict, VerificationVerdict.UNKNOWN)
        self.assertEqual(
            absent_key.predicate_results[0].reason, ChangeUnknownReason.CHANGE_NOT_OBSERVED
        )
        wrong_kind = ChangeCooccurrencePredicate(
            "p", ChangeEventKey("svc-pre"), ChangeKind.ROLLBACK, ChangePhaseConstraint.WITHIN_WINDOW
        )
        result = verify_change_hypothesis(hypothesis((wrong_kind,)), base_ledger())
        self.assertEqual(
            result.predicate_results[0].reason, ChangeUnknownReason.CHANGE_NOT_OBSERVED
        )

    def test_within_window_union_and_out_of_window_refutation(self) -> None:
        within_post = ChangeCooccurrencePredicate(
            "p",
            ChangeEventKey("svc-post"),
            ChangeKind.ROLLBACK,
            ChangePhaseConstraint.WITHIN_WINDOW,
        )
        self.assertEqual(
            verify_change_hypothesis(hypothesis((within_post,)), base_ledger()).verdict,
            VerificationVerdict.SUPPORTED,
        )
        for constraint in ChangePhaseConstraint:
            with self.subTest(constraint=constraint.value):
                out_of_window = ChangeCooccurrencePredicate(
                    "p", ChangeEventKey("svc-early"), ChangeKind.CONFIGURATION, constraint
                )
                self.assertEqual(
                    verify_change_hypothesis(hypothesis((out_of_window,)), base_ledger()).verdict,
                    VerificationVerdict.REFUTED,
                )

    def test_document_aggregates_child_evidence_ids(self) -> None:
        result = verify_change_hypothesis(
            hypothesis((supported("p1"), refuted("p2")), composition=HypothesisComposition.ALL),
            base_ledger(),
        )
        expected_supporting = tuple(
            eid for child in result.predicate_results for eid in child.supporting_evidence_ids
        )
        expected_contradicting = tuple(
            eid for child in result.predicate_results for eid in child.contradicting_evidence_ids
        )
        self.assertEqual(result.supporting_evidence_ids, expected_supporting)
        self.assertEqual(result.contradicting_evidence_ids, expected_contradicting)


class ChangeCompositionTruthTableTests(unittest.TestCase):
    def _expected(self, composition: HypothesisComposition, kinds: tuple[str, ...]) -> str:
        if composition is HypothesisComposition.ALL:
            if "R" in kinds:
                return "refuted"
            if "U" in kinds:
                return "unknown"
            return "supported"
        if "S" in kinds:
            return "supported"
        if "U" in kinds:
            return "unknown"
        return "refuted"

    def test_all_and_any_three_valued_tables_retain_children(self) -> None:
        ledger = base_ledger()
        for composition in HypothesisComposition:
            for length in (1, 2, 3):
                for kinds in itertools.product("SRU", repeat=length):
                    with self.subTest(composition=composition.value, kinds=kinds):
                        predicates = tuple(
                            BUILDERS[kind](f"p{index}") for index, kind in enumerate(kinds)
                        )
                        result = verify_change_hypothesis(
                            hypothesis(predicates, composition=composition), ledger
                        )
                        self.assertEqual(result.verdict.value, self._expected(composition, kinds))
                        self.assertEqual(len(result.predicate_results), length)
                        observed = tuple(
                            child.verdict.value[0].upper() for child in result.predicate_results
                        )
                        self.assertEqual(observed, kinds)


if __name__ == "__main__":
    unittest.main()
