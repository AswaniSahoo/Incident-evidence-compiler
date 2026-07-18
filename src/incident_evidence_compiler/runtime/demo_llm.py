"""A labelled non-model smoke ``LLMClient`` (ADR 0016).

``FirstSignalLLMClient`` deterministically proposes an ``increase`` predicate on the
lexicographically-first allowed signal. It exists so the system can boot and complete the
pipeline end-to-end with zero credentials (local smoke, container CI). It is NOT a model and
makes no accuracy claim; the real arms are the Gemini developer/vertex clients. Its output is
still routed through the untrusted-output parser exactly like any provider's.
"""

import json

from ..llm.client import HypothesisRequest, LLMProposal


class FirstSignalLLMClient:
    """Deterministically propose one increase predicate on the first allowed signal."""

    async def propose_metric_hypotheses(self, request: HypothesisRequest) -> LLMProposal:
        signals = sorted(key.value for key in request.allowed_signals)
        predicates = (
            [{"predicate_id": "p1", "signal_key": signals[0], "expected_direction": "increase"}]
            if signals
            else []
        )
        payload = {
            "hypothesis_id": "smoke-h1",
            "tenant_id": request.tenant.value,
            "incident_id": request.incident.value,
            "run_id": request.run.value,
            "semantics": "descriptive",
            "composition": "any",
            "predicates": predicates,
        }
        return LLMProposal(raw_json=json.dumps(payload), model="smoke:first-signal")
