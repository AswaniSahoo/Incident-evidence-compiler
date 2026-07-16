from __future__ import annotations

import json
import logging
import math
import unittest
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

from incident_evidence_compiler.domain.baseline import (
    BaselinePolicy,
    SignalBaselineInput,
    rank_metric_shifts,
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
from incident_evidence_compiler.domain.serialization import (
    VERIFICATION_SCHEMA_VERSION,
    CanonicalSerializationError,
    ledger_json,
    verification_json,
)
from incident_evidence_compiler.domain.verifier import (
    HypothesisVerificationResult,
    ObservedDirection,
    UnknownReason,
    VerificationVerdict,
    verify_hypothesis,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def window() -> IncidentWindow:
    return IncidentWindow(BASE, BASE + timedelta(minutes=10), BASE + timedelta(minutes=20))


def baseline_input(
    name: str,
    pre: tuple[float, ...],
    post: tuple[float, ...],
    *,
    floor: float = 1.0,
) -> SignalBaselineInput:
    points = tuple(
        MetricPoint(BASE + timedelta(minutes=index), value) for index, value in enumerate(pre)
    ) + tuple(
        MetricPoint(BASE + timedelta(minutes=10 + index), value) for index, value in enumerate(post)
    )
    return SignalBaselineInput(MetricSignal(SignalKey(name), points), floor)


def ledger_for(*inputs: SignalBaselineInput) -> MetricEvidenceLedger:
    result = rank_metric_shifts(
        window(),
        inputs,
        BaselinePolicy(2, 1.0, 0.0, 0.125),
    )
    return compile_metric_shift_ledger(
        TenantId("租户-01"),
        IncidentId("incident-01"),
        RunId("run-01"),
        window(),
        result,
    )


def representative_ledger(*, reverse: bool = False) -> MetricEvidenceLedger:
    inputs = (
        baseline_input("z-memory", (4.0, 4.0), (1.0, 1.0), floor=0.5),
        baseline_input("A-cpu", (0.0, 0.0), (2.0, 2.0)),
        baseline_input("é-short", (1.0,), (2.0, 2.0), floor=2.0),
    )
    return ledger_for(*(tuple(reversed(inputs)) if reverse else inputs))


def representative_verification(ledger: MetricEvidenceLedger) -> HypothesisVerificationResult:
    hypothesis = HypothesisDocument(
        "hypothesis-\N{GREEK SMALL LETTER ALPHA}",
        ledger.tenant_id,
        ledger.incident_id,
        ledger.run_id,
        HypothesisSemantics.DESCRIPTIVE,
        HypothesisComposition.ALL,
        (
            MetricShiftPredicate(
                "p-memory",
                SignalKey("z-memory"),
                ExpectedDirection.DECREASE,
            ),
            MetricShiftPredicate(
                "p-cpu-opposite",
                SignalKey("A-cpu"),
                ExpectedDirection.DECREASE,
            ),
            MetricShiftPredicate(
                "p-missing",
                SignalKey("missing"),
                ExpectedDirection.INCREASE,
            ),
        ),
    )
    return verify_hypothesis(hypothesis, ledger)


def parsed(serialized: str) -> dict[str, object]:
    value: object = json.loads(serialized)
    if not isinstance(value, dict):
        raise AssertionError("expected JSON object")
    return cast(dict[str, object], value)


class CanonicalLedgerTests(unittest.TestCase):
    def test_ledger_json_is_utf8_byte_stable_canonical_and_order_invariant(self) -> None:
        first = ledger_json(representative_ledger())
        repeated = ledger_json(representative_ledger())
        permuted = ledger_json(representative_ledger(reverse=True))

        self.assertEqual(first.encode("utf-8"), repeated.encode("utf-8"))
        self.assertEqual(first.encode("utf-8"), permuted.encode("utf-8"))
        self.assertIn("租户-01", first)
        self.assertTrue(first.endswith("\n"))
        self.assertFalse(first.endswith("\n\n"))
        self.assertEqual(first.count("\n"), 1)
        self.assertNotIn(": ", first)
        self.assertNotIn(", ", first)
        self.assertEqual(
            first,
            json.dumps(
                parsed(first),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
        )

        payload = parsed(first)
        entries = cast(list[dict[str, object]], payload["entries"])
        self.assertEqual(
            [entry["signal_key"] for entry in entries],
            ["A-cpu", "z-memory", "é-short"],
        )

    def test_ledger_key_snapshot_and_float_hex_contract_are_explicit(self) -> None:
        payload = parsed(ledger_json(representative_ledger()))
        self.assertEqual(
            set(payload),
            {
                "decision",
                "entries",
                "incident_id",
                "incident_window",
                "policy",
                "run_id",
                "schema_version",
                "tenant_id",
            },
        )
        self.assertEqual(payload["schema_version"], "metric-evidence-ledger.v1")
        self.assertEqual(
            set(cast(dict[str, object], payload["incident_window"])),
            {"end", "injection", "start"},
        )
        policy = cast(dict[str, object], payload["policy"])
        self.assertEqual(
            set(policy),
            {
                "minimum_margin",
                "minimum_points_per_window",
                "minimum_score",
                "relative_scale_floor",
            },
        )
        self.assertEqual(policy["minimum_points_per_window"], 2)
        for key in ("minimum_margin", "minimum_score", "relative_scale_floor"):
            self.assertEqual(policy[key], float.fromhex(cast(str, policy[key])).hex())

        decision = cast(dict[str, object], payload["decision"])
        self.assertEqual(
            set(decision),
            {
                "abstention_reason",
                "candidate_signal_keys",
                "eligible_signal_count",
                "kind",
                "lead",
                "second_score",
                "top_score",
            },
        )
        entries = cast(list[dict[str, object]], payload["entries"])
        self.assertEqual(
            set(entries[0]),
            {
                "absolute_scale_floor",
                "candidate",
                "eligible",
                "evidence_id",
                "post_point_count",
                "pre_point_count",
                "relative_scale_floor",
                "signal_key",
            },
        )
        candidate = cast(dict[str, object], entries[0]["candidate"])
        self.assertEqual(
            set(candidate),
            {
                "absolute_scale_floor",
                "post_median",
                "post_point_count",
                "pre_mad",
                "pre_median",
                "pre_point_count",
                "relative_scale_floor",
                "scale",
                "signal_key",
                "signed_score",
                "suspicion_score",
            },
        )
        float_keys = {
            "absolute_scale_floor",
            "post_median",
            "pre_mad",
            "pre_median",
            "relative_scale_floor",
            "scale",
            "signed_score",
            "suspicion_score",
        }
        for key in float_keys:
            encoded = cast(str, candidate[key])
            self.assertEqual(encoded, float.fromhex(encoded).hex())


class CanonicalVerificationTests(unittest.TestCase):
    def test_verification_json_is_byte_stable_and_preserves_declaration_arrays(self) -> None:
        result = representative_verification(representative_ledger())
        first = verification_json(result)
        second = verification_json(result)
        self.assertEqual(first.encode("utf-8"), second.encode("utf-8"))
        self.assertIn("hypothesis-\N{GREEK SMALL LETTER ALPHA}", first)
        self.assertTrue(first.endswith("\n"))
        self.assertFalse(first.endswith("\n\n"))
        self.assertEqual(first.count("\n"), 1)
        self.assertEqual(
            first,
            json.dumps(
                parsed(first),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
        )

        payload = parsed(first)
        children = cast(list[dict[str, object]], payload["predicate_results"])
        self.assertEqual(
            [child["predicate_id"] for child in children],
            ["p-memory", "p-cpu-opposite", "p-missing"],
        )
        self.assertEqual(
            payload["supporting_evidence_ids"],
            children[0]["supporting_evidence_ids"],
        )
        self.assertEqual(
            payload["contradicting_evidence_ids"],
            children[1]["contradicting_evidence_ids"],
        )

    def test_verification_key_snapshot_and_float_hex_contract_are_explicit(self) -> None:
        payload = parsed(verification_json(representative_verification(representative_ledger())))
        self.assertEqual(
            set(payload),
            {
                "composition",
                "contradicting_evidence_ids",
                "hypothesis_id",
                "predicate_results",
                "reason",
                "schema_version",
                "supporting_evidence_ids",
                "verdict",
            },
        )
        self.assertEqual(payload["schema_version"], VERIFICATION_SCHEMA_VERSION)
        children = cast(list[dict[str, object]], payload["predicate_results"])
        expected_child_keys = {
            "contradicting_evidence_ids",
            "minimum_score",
            "observed_direction",
            "predicate_id",
            "reason",
            "supporting_evidence_ids",
            "verdict",
        }
        self.assertTrue(children)
        for child in children:
            self.assertEqual(set(child), expected_child_keys)
            threshold = cast(str, child["minimum_score"])
            self.assertEqual(threshold, float.fromhex(threshold).hex())


class FailClosedAndLeakageTests(unittest.TestCase):
    def test_nonfinite_ledger_and_verification_fields_fail_closed(self) -> None:
        ledger = representative_ledger()
        candidate = ledger.entries[0].candidate
        self.assertIsNotNone(candidate)
        assert candidate is not None
        forged_entry = replace(
            ledger.entries[0],
            candidate=replace(candidate, signed_score=math.nan),
        )
        forged_ledgers = (
            replace(ledger, entries=(forged_entry, *ledger.entries[1:])),
            replace(ledger, decision=replace(ledger.decision, top_score=math.inf)),
        )
        for forged in forged_ledgers:
            with self.subTest(forged=repr(forged)):
                with self.assertRaises(CanonicalSerializationError) as caught:
                    ledger_json(forged)
                self.assertEqual(str(caught.exception), "canonical_serialization_failed")

        result = representative_verification(ledger)
        child = replace(result.predicate_results[0], minimum_score=math.nan)
        forged_result = replace(
            result,
            predicate_results=(child, *result.predicate_results[1:]),
        )
        with self.assertRaises(CanonicalSerializationError) as caught:
            verification_json(forged_result)
        self.assertEqual(str(caught.exception), "canonical_serialization_failed")

    def test_only_exact_supported_artifacts_are_accepted_without_repr_or_str_fallback(self) -> None:
        class Canary:
            repr_calls = 0
            str_calls = 0

            def __repr__(self) -> str:
                type(self).repr_calls += 1
                return "REPR_SECRET_CANARY"

            def __str__(self) -> str:
                type(self).str_calls += 1
                return "STR_SECRET_CANARY"

        value = Canary()
        serializers: tuple[tuple[str, Callable[[], str]], ...] = (
            ("ledger_json", lambda: ledger_json(cast(MetricEvidenceLedger, value))),
            (
                "verification_json",
                lambda: verification_json(cast(HypothesisVerificationResult, value)),
            ),
        )
        for name, serialize in serializers:
            with self.subTest(serializer=name):
                with self.assertRaises(CanonicalSerializationError) as caught:
                    serialize()
                error_text = str(caught.exception) + repr(caught.exception)
                self.assertNotIn("SECRET_CANARY", error_text)
        self.assertEqual(Canary.repr_calls, 0)
        self.assertEqual(Canary.str_calls, 0)

    def test_source_label_path_secret_and_custom_repr_canaries_never_cross_boundary(self) -> None:
        source_path = r"C:\private\RCAEval\service-fault.csv"
        service_label = "SERVICE_LABEL_CANARY"
        fault_label = "FAULT_LABEL_CANARY"
        credential = "API_SECRET_CANARY"

        class TaintedPoints:
            def __init__(self) -> None:
                self.source_path = source_path
                self.service_label = service_label
                self.fault_label = fault_label
                self.credential = credential
                self._points = (
                    MetricPoint(BASE, 0.0),
                    MetricPoint(BASE + timedelta(minutes=1), 0.0),
                    MetricPoint(BASE + timedelta(minutes=10), 2.0),
                    MetricPoint(BASE + timedelta(minutes=11), 2.0),
                )

            def __iter__(self) -> Iterator[MetricPoint]:
                return iter(self._points)

            def __repr__(self) -> str:
                return "CUSTOM_REPR_CANARY"

        item = SignalBaselineInput(
            MetricSignal(SignalKey("safe-signal"), TaintedPoints()),
            1.0,
        )
        ledger = ledger_for(item)
        document = HypothesisDocument(
            "safe-hypothesis",
            ledger.tenant_id,
            ledger.incident_id,
            ledger.run_id,
            HypothesisSemantics.DESCRIPTIVE,
            HypothesisComposition.ALL,
            (
                MetricShiftPredicate(
                    "safe-predicate",
                    SignalKey("safe-signal"),
                    ExpectedDirection.INCREASE,
                ),
            ),
        )
        result = verify_hypothesis(document, ledger)
        boundary_text = (
            ledger_json(ledger)
            + verification_json(result)
            + repr(ledger)
            + repr(result)
            + repr(result.predicate_results[0])
        )
        for canary in (
            source_path,
            service_label,
            fault_label,
            credential,
            "CUSTOM_REPR_CANARY",
        ):
            self.assertNotIn(canary, boundary_text)

    def test_unpaired_surrogate_is_rejected_as_not_utf8_compatible(self) -> None:
        ledger = representative_ledger()
        forged = replace(ledger, tenant_id=TenantId("bad\ud800tenant"))
        with self.assertRaises(CanonicalSerializationError):
            ledger_json(forged)


class VerificationSerializerAdversarialTests(unittest.TestCase):
    def assert_serialization_failure(self, result: HypothesisVerificationResult) -> None:
        with self.assertRaises(CanonicalSerializationError) as caught:
            verification_json(result)
        self.assertEqual(str(caught.exception), "canonical_serialization_failed")

    def test_ledger_serializer_rejects_stale_evidence_id(self) -> None:
        ledger = representative_ledger()
        stale_entry = replace(ledger.entries[0], evidence_id=EvidenceId("sha256:" + "0" * 64))
        with self.assertRaises(CanonicalSerializationError):
            ledger_json(replace(ledger, entries=(stale_entry, *ledger.entries[1:])))

    def test_context_gate_rejects_evidence_and_decisive_children(self) -> None:
        ledger = representative_ledger()
        gated = verify_hypothesis(
            HypothesisDocument(
                "gated",
                TenantId("foreign"),
                ledger.incident_id,
                ledger.run_id,
                HypothesisSemantics.DESCRIPTIVE,
                HypothesisComposition.ALL,
                (
                    MetricShiftPredicate(
                        "p",
                        ledger.entries[0].signal_key,
                        ExpectedDirection.INCREASE,
                    ),
                ),
            ),
            ledger,
        )
        evidence_id = ledger.entries[0].evidence_id
        child = gated.predicate_results[0]
        leaked_unknown = replace(child, supporting_evidence_ids=(evidence_id,))
        self.assert_serialization_failure(
            replace(
                gated,
                predicate_results=(leaked_unknown,),
                supporting_evidence_ids=(evidence_id,),
            )
        )

        decisive = replace(
            child,
            verdict=VerificationVerdict.SUPPORTED,
            reason=None,
            observed_direction=ObservedDirection.INCREASE,
            supporting_evidence_ids=(evidence_id,),
        )
        self.assert_serialization_failure(
            replace(
                gated,
                predicate_results=(decisive,),
                supporting_evidence_ids=(evidence_id,),
            )
        )

    def test_rejects_inconsistent_aggregate_verdict_and_reason(self) -> None:
        ledger = representative_ledger()
        supported = verify_hypothesis(
            HypothesisDocument(
                "supported",
                ledger.tenant_id,
                ledger.incident_id,
                ledger.run_id,
                HypothesisSemantics.DESCRIPTIVE,
                HypothesisComposition.ALL,
                (
                    MetricShiftPredicate(
                        "p",
                        SignalKey("A-cpu"),
                        ExpectedDirection.INCREASE,
                    ),
                ),
            ),
            ledger,
        )
        self.assert_serialization_failure(replace(supported, verdict=VerificationVerdict.REFUTED))
        self.assert_serialization_failure(replace(supported, reason=UnknownReason.CONTEXT_MISMATCH))

    def test_sanitized_failures_emit_no_canary_logs(self) -> None:
        records: list[logging.LogRecord] = []

        class Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        root = logging.getLogger()
        handler = Capture()
        root.addHandler(handler)
        try:
            ledger = representative_ledger()
            forged = replace(ledger, tenant_id=TenantId("LOG_SECRET\ud800"))
            with self.assertRaises(CanonicalSerializationError):
                ledger_json(forged)
        finally:
            root.removeHandler(handler)
        self.assertEqual(records, [])

    def test_malformed_exact_result_is_sanitized(self) -> None:
        malformed = object.__new__(HypothesisVerificationResult)
        self.assert_serialization_failure(malformed)

    def test_unknown_reason_direction_matrix_is_enforced(self) -> None:
        result = representative_verification(representative_ledger())
        unknown = result.predicate_results[2]
        for reason in (
            UnknownReason.SIGNAL_NOT_FOUND,
            UnknownReason.INSUFFICIENT_EVIDENCE,
            UnknownReason.NO_DIRECTIONAL_SHIFT,
        ):
            with self.subTest(reason=reason):
                forged_child = replace(
                    unknown,
                    reason=reason,
                    observed_direction=ObservedDirection.INCREASE,
                )
                self.assert_serialization_failure(
                    replace(result, predicate_results=(*result.predicate_results[:2], forged_child))
                )
        weak_without_direction = replace(
            unknown,
            reason=UnknownReason.WEAK_EVIDENCE,
            observed_direction=None,
        )
        self.assert_serialization_failure(
            replace(
                result, predicate_results=(*result.predicate_results[:2], weak_without_direction)
            )
        )


if __name__ == "__main__":
    unittest.main()
