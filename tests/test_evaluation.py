"""Hermetic tests for the Phase 7 evaluation harness.

Everything here is deterministic and runs against synthetic, in-memory cases plus the
committed leakage fixture and the ``FakeLLMClient`` — no network, database, credentials,
or out-of-repo data. The real RCAEval RE2 evaluation is driven by ``scripts/run_evaluation.py``
against an out-of-repo split and is not part of this gate.
"""

import asyncio
import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from incident_evidence_compiler.domain import (
    CaseId,
    IncidentWindow,
    MetricPoint,
    MetricSignal,
    SignalKey,
)
from incident_evidence_compiler.evaluation.harness import (
    Arm,
    aggregate,
    evaluate_batch,
    predict_services_baseline,
    score_case,
    service_of,
    summary_json,
    to_baseline_inputs,
)
from incident_evidence_compiler.evaluation.harness.scoring import CaseScore
from incident_evidence_compiler.evaluation.rcaeval import (
    EvaluationBatch,
    EvaluationSidecar,
    InvestigationCase,
    RcaevalAdapter,
    RcaevalSplit,
    SidecarEntry,
)
from incident_evidence_compiler.llm import HypothesisRequest, LLMProposal

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "rcaeval" / "RE2-OB"
_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _window() -> IncidentWindow:
    return IncidentWindow(
        start=_BASE,
        injection=_BASE + timedelta(minutes=10),
        end=_BASE + timedelta(minutes=20),
    )


def _signal(name: str, pre_value: float, post_value: float) -> MetricSignal:
    pre = [MetricPoint(_BASE + timedelta(minutes=i), pre_value) for i in range(4)]
    post = [MetricPoint(_BASE + timedelta(minutes=10 + i), post_value) for i in range(4)]
    return MetricSignal(SignalKey(name), tuple(pre + post))


def _case(
    case_ref: int,
    signals: tuple[MetricSignal, ...],
) -> InvestigationCase:
    case_id = CaseId(UUID(f"00000000-0000-4000-8000-{case_ref:012d}"))
    return InvestigationCase(case_id, RcaevalSplit.OB, _window(), signals)


def _batch(pairs: list[tuple[InvestigationCase, str]]) -> EvaluationBatch:
    entries = tuple(
        SidecarEntry(
            case_id=case.case_id,
            split=RcaevalSplit.OB,
            source_locator=f"REDACTED/{index}",
            root_cause_service=truth,
            injected_fault_type="fault",
            repetition="1",
            answer_labels=(truth, "fault"),
        )
        for index, (case, truth) in enumerate(pairs)
    )
    sidecar = EvaluationSidecar("1.2.0", "bc49dbd85bd14032101fb9a69a5a37e9d6d55178", entries)
    return EvaluationBatch(tuple(case for case, _ in pairs), sidecar)


def _proposal(case: InvestigationCase, signal_key: str, direction: str = "increase") -> str:
    case_ref = str(case.case_id)
    return json.dumps(
        {
            "hypothesis_id": "h1",
            "tenant_id": "evaluation",
            "incident_id": case_ref,
            "run_id": case_ref,
            "semantics": "descriptive",
            "composition": "all",
            "predicates": [
                {"predicate_id": "p1", "signal_key": signal_key, "expected_direction": direction}
            ],
        }
    )


class _ScriptedLLM:
    """Return one scripted raw JSON keyed by the incident id (the case reference)."""

    def __init__(self, by_incident: dict[str, str]) -> None:
        self._by_incident = by_incident

    async def propose_metric_hypotheses(self, request: HypothesisRequest) -> LLMProposal:
        return LLMProposal(raw_json=self._by_incident[request.incident.value])


class ServiceMappingTests(unittest.TestCase):
    def test_service_is_everything_before_the_final_underscore(self) -> None:
        self.assertEqual(service_of("checkoutservice_cpu"), "checkoutservice")
        self.assertEqual(service_of("checkoutservice_latency-90"), "checkoutservice")
        self.assertEqual(service_of("frontend-external_workload"), "frontend-external")
        # A column with no underscore is its own service.
        self.assertEqual(service_of("redis"), "redis")


class ScaleFloorTests(unittest.TestCase):
    def test_floor_is_strictly_positive_and_scales_with_magnitude(self) -> None:
        big = _signal("svc_mem", 1.0e8, 1.0e8)
        small = _signal("svc_cpu", 0.2, 0.2)
        inputs = to_baseline_inputs((big, small))
        floors = {item.signal.key.value: item.absolute_scale_floor for item in inputs}
        self.assertGreater(floors["svc_mem"], floors["svc_cpu"])
        self.assertTrue(all(value > 0.0 for value in floors.values()))

    def test_empty_signal_still_gets_a_positive_floor(self) -> None:
        empty = MetricSignal(SignalKey("svc_gap"), ())
        (item,) = to_baseline_inputs((empty,))
        self.assertGreater(item.absolute_scale_floor, 0.0)


class ScoringTests(unittest.TestCase):
    def test_case_score_derives_top_k_and_reciprocal_rank(self) -> None:
        hit_first = score_case(("a", "b", "c"), "a", abstained=False)
        self.assertTrue(hit_first.top1)
        self.assertTrue(hit_first.top3)
        self.assertEqual(hit_first.reciprocal_rank, 1.0)

        hit_third = score_case(("a", "b", "c"), "c", abstained=False)
        self.assertFalse(hit_third.top1)
        self.assertTrue(hit_third.top3)
        self.assertAlmostEqual(hit_third.reciprocal_rank, 1 / 3)

        miss = score_case(("a", "b", "c", "d"), "d", abstained=False)
        self.assertFalse(miss.top3)
        self.assertAlmostEqual(miss.reciprocal_rank, 1 / 4)

        abstained = score_case(("a",), "a", abstained=True)
        self.assertIsNone(abstained.hit_rank)
        self.assertEqual(abstained.reciprocal_rank, 0.0)

    def test_aggregate_reports_overall_and_answered_metrics(self) -> None:
        scores = [
            CaseScore(
                abstained=False, hit_rank=1, predicted_service_count=3, invalid_evidence_id_count=0
            ),
            CaseScore(
                abstained=False, hit_rank=3, predicted_service_count=3, invalid_evidence_id_count=0
            ),
            CaseScore(
                abstained=True,
                hit_rank=None,
                predicted_service_count=0,
                invalid_evidence_id_count=0,
            ),
            CaseScore(
                abstained=False,
                hit_rank=None,
                predicted_service_count=5,
                invalid_evidence_id_count=2,
            ),
        ]
        summary = aggregate(scores)
        self.assertEqual(summary.case_count, 4)
        self.assertEqual(summary.abstained_count, 1)
        self.assertEqual(summary.answered_count, 3)
        self.assertAlmostEqual(summary.abstention_rate, 0.25)
        self.assertAlmostEqual(summary.top1_accuracy, 1 / 4)
        self.assertAlmostEqual(summary.top3_accuracy, 2 / 4)
        self.assertAlmostEqual(summary.top1_accuracy_answered, 1 / 3)
        self.assertAlmostEqual(summary.mrr, (1.0 + 1 / 3) / 4)
        self.assertEqual(summary.invalid_evidence_id_count, 2)

    def test_empty_aggregate_is_all_zero(self) -> None:
        summary = aggregate([])
        self.assertEqual(summary.case_count, 0)
        self.assertEqual(summary.top1_accuracy, 0.0)
        self.assertEqual(summary.mrr_answered, 0.0)


class BaselineArmTests(unittest.TestCase):
    def test_shifted_service_is_ranked_first(self) -> None:
        case = _case(
            1,
            (
                _signal("checkoutservice_cpu", 1.0, 100.0),
                _signal("frontend_cpu", 5.0, 5.0),
            ),
        )
        services, abstained = predict_services_baseline(case)
        self.assertFalse(abstained)
        self.assertEqual(services[0], "checkoutservice")

    def test_flat_case_abstains(self) -> None:
        case = _case(2, (_signal("checkoutservice_cpu", 3.0, 3.0),))
        _services, abstained = predict_services_baseline(case)
        self.assertTrue(abstained)

    def test_evaluate_batch_baseline_scores_top1(self) -> None:
        case = _case(
            3,
            (
                _signal("checkoutservice_cpu", 1.0, 100.0),
                _signal("frontend_cpu", 5.0, 5.0),
            ),
        )
        summary = asyncio.run(evaluate_batch(_batch([(case, "checkoutservice")])))
        self.assertEqual(summary.case_count, 1)
        self.assertEqual(summary.top1_accuracy, 1.0)
        self.assertEqual(summary.invalid_evidence_id_count, 0)


class GeminiArmTests(unittest.TestCase):
    def test_verified_support_predicts_service_with_zero_invalid_ids(self) -> None:
        case = _case(
            4,
            (
                _signal("checkoutservice_cpu", 1.0, 100.0),
                _signal("frontend_cpu", 5.0, 5.0),
            ),
        )
        client = _ScriptedLLM({str(case.case_id): _proposal(case, "checkoutservice_cpu")})
        summary = asyncio.run(
            evaluate_batch(_batch([(case, "checkoutservice")]), arm=Arm.GEMINI, llm_client=client)
        )
        self.assertEqual(summary.top1_accuracy, 1.0)
        self.assertEqual(summary.invalid_evidence_id_count, 0)
        self.assertEqual(summary.abstained_count, 0)

    def test_refuted_direction_yields_no_prediction(self) -> None:
        case = _case(
            5,
            (
                _signal("checkoutservice_cpu", 1.0, 100.0),
                _signal("frontend_cpu", 5.0, 5.0),
            ),
        )
        # The observed shift is an increase; asserting a decrease is REFUTED, not SUPPORTED.
        client = _ScriptedLLM(
            {str(case.case_id): _proposal(case, "checkoutservice_cpu", direction="decrease")}
        )
        summary = asyncio.run(
            evaluate_batch(_batch([(case, "checkoutservice")]), arm=Arm.GEMINI, llm_client=client)
        )
        self.assertEqual(summary.abstained_count, 1)
        self.assertEqual(summary.top1_accuracy, 0.0)

    def test_malformed_output_is_scored_as_abstention(self) -> None:
        case = _case(6, (_signal("checkoutservice_cpu", 1.0, 100.0),))
        client = _ScriptedLLM({str(case.case_id): "not-json"})
        summary = asyncio.run(
            evaluate_batch(_batch([(case, "checkoutservice")]), arm=Arm.GEMINI, llm_client=client)
        )
        self.assertEqual(summary.abstained_count, 1)
        self.assertEqual(summary.invalid_evidence_id_count, 0)

    def test_gemini_arm_requires_a_client(self) -> None:
        case = _case(7, (_signal("checkoutservice_cpu", 1.0, 100.0),))
        with self.assertRaises(ValueError):
            asyncio.run(evaluate_batch(_batch([(case, "checkoutservice")]), arm=Arm.GEMINI))


class ArtifactLeakageTests(unittest.TestCase):
    def test_aggregate_artifact_contains_no_labels_or_locator(self) -> None:
        # Load the committed leakage fixture (CANARYSERVICE/OTHERSERVICE/DO_NOT_LEAK_PATH)
        # through the real adapter, evaluate it, and confirm the aggregate surface is clean.
        batch = RcaevalAdapter().load(FIXTURE_ROOT, "OB")
        summary = asyncio.run(evaluate_batch(batch))
        rendered = summary_json(summary)
        for canary in ("CANARYSERVICE", "CANARYFAULT", "OTHERSERVICE", "DO_NOT_LEAK_PATH"):
            with self.subTest(canary=canary):
                self.assertNotIn(canary, rendered)


if __name__ == "__main__":
    unittest.main()
