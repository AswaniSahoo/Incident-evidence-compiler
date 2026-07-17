"""Behavior and failure-semantics tests for the LLM provider boundary.

Hermetic: everything runs against the deterministic in-memory fake and the pure parser
with no network, model SDK, or credentials, so it belongs in the locked gate. The parser
is exercised as an untrusted-input boundary: valid model output maps to a real domain
document, and every fuzz/failure shape raises the correct stable typed error.
"""

import json
import unittest

from incident_evidence_compiler.domain.hypotheses import (
    MAX_PREDICATES,
    ExpectedDirection,
    HypothesisComposition,
    HypothesisDocument,
    HypothesisSemantics,
)
from incident_evidence_compiler.domain.identifiers import RunId, TenantId
from incident_evidence_compiler.domain.metrics import SignalKey
from incident_evidence_compiler.llm import (
    MAX_PROPOSAL_CHARS,
    EmptyProposalError,
    FakeLLMClient,
    HypothesisRequest,
    LLMClient,
    LLMProposal,
    MalformedProposalError,
    ProposalSchemaError,
    ProposalTooLargeError,
    TooManyPredicatesError,
    UnauthorizedEntityError,
    parse_metric_hypothesis,
)

_ALLOWED = frozenset({SignalKey("checkout.latency.p99"), SignalKey("checkout.error.rate")})


def _predicate(
    *,
    predicate_id: str = "p1",
    signal_key: str = "checkout.latency.p99",
    expected_direction: str = "increase",
) -> dict[str, str]:
    return {
        "predicate_id": predicate_id,
        "signal_key": signal_key,
        "expected_direction": expected_direction,
    }


def _proposal(
    *,
    predicates: list[dict[str, str]] | None = None,
    semantics: str = "descriptive",
    composition: str = "any",
) -> str:
    payload: dict[str, object] = {
        "hypothesis_id": "hyp-1",
        "tenant_id": "tenant-a",
        "incident_id": "inc-1",
        "run_id": "run-1",
        "semantics": semantics,
        "composition": composition,
        "predicates": [_predicate()] if predicates is None else predicates,
    }
    return json.dumps(payload)


def _request() -> HypothesisRequest:
    return HypothesisRequest(
        tenant=TenantId("tenant-a"),
        run=RunId("run-1"),
        allowed_signals=_ALLOWED,
    )


class FakeLLMClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_returns_scripted_proposals_in_order(self) -> None:
        client: LLMClient = FakeLLMClient([_proposal(), "not-json"])
        first = await client.propose_metric_hypotheses(_request())
        second = await client.propose_metric_hypotheses(_request())
        self.assertIsInstance(first, LLMProposal)
        self.assertEqual(first.raw_json, _proposal())
        self.assertEqual(second.raw_json, "not-json")

    async def test_scripted_valid_proposal_parses_to_document(self) -> None:
        client = FakeLLMClient([_proposal()])
        proposal = await client.propose_metric_hypotheses(_request())
        document = parse_metric_hypothesis(proposal.raw_json, allowed_signals=_ALLOWED)
        self.assertIsInstance(document, HypothesisDocument)


class ParseMetricHypothesisTest(unittest.TestCase):
    def test_happy_path_returns_hypothesis_document(self) -> None:
        document = parse_metric_hypothesis(_proposal(), allowed_signals=_ALLOWED)
        self.assertIsInstance(document, HypothesisDocument)
        self.assertEqual(document.tenant_id, TenantId("tenant-a"))
        self.assertEqual(document.run_id, RunId("run-1"))
        self.assertEqual(document.semantics, HypothesisSemantics.DESCRIPTIVE)
        self.assertEqual(document.composition, HypothesisComposition.ANY)
        self.assertEqual(len(document.predicates), 1)
        predicate = document.predicates[0]
        self.assertEqual(predicate.signal_key, SignalKey("checkout.latency.p99"))
        self.assertEqual(predicate.expected_direction, ExpectedDirection.INCREASE)

    def test_non_json_raises_malformed(self) -> None:
        with self.assertRaises(MalformedProposalError):
            parse_metric_hypothesis("{not valid json", allowed_signals=_ALLOWED)

    def test_json_non_object_raises_schema(self) -> None:
        with self.assertRaises(ProposalSchemaError):
            parse_metric_hypothesis("[1, 2, 3]", allowed_signals=_ALLOWED)

    def test_oversized_input_raises_too_large(self) -> None:
        oversized = "x" * (MAX_PROPOSAL_CHARS + 1)
        with self.assertRaises(ProposalTooLargeError):
            parse_metric_hypothesis(oversized, allowed_signals=_ALLOWED)

    def test_empty_input_raises_empty(self) -> None:
        with self.assertRaises(EmptyProposalError):
            parse_metric_hypothesis("   \n\t ", allowed_signals=_ALLOWED)

    def test_invalid_predicate_structure_raises_schema(self) -> None:
        raw = _proposal(predicates=[_predicate(expected_direction="sideways")])
        with self.assertRaises(ProposalSchemaError):
            parse_metric_hypothesis(raw, allowed_signals=_ALLOWED)

    def test_non_object_predicate_raises_schema(self) -> None:
        payload: dict[str, object] = {
            "hypothesis_id": "hyp-1",
            "tenant_id": "tenant-a",
            "incident_id": "inc-1",
            "run_id": "run-1",
            "semantics": "descriptive",
            "composition": "any",
            "predicates": ["not-an-object"],
        }
        with self.assertRaises(ProposalSchemaError):
            parse_metric_hypothesis(json.dumps(payload), allowed_signals=_ALLOWED)

    def test_signal_outside_allow_list_raises_unauthorized(self) -> None:
        raw = _proposal(predicates=[_predicate(signal_key="database.connections.active")])
        with self.assertRaises(UnauthorizedEntityError):
            parse_metric_hypothesis(raw, allowed_signals=_ALLOWED)

    def test_too_many_predicates_raises(self) -> None:
        predicates = [
            _predicate(predicate_id=f"p{index}", signal_key=f"signal-{index}")
            for index in range(MAX_PREDICATES + 1)
        ]
        raw = _proposal(predicates=predicates)
        with self.assertRaises(TooManyPredicatesError):
            parse_metric_hypothesis(raw, allowed_signals=_ALLOWED)


if __name__ == "__main__":
    unittest.main()
