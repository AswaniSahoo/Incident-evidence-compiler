"""Deterministic in-memory ``LLMClient`` for tests.

``FakeLLMClient`` replays a scripted sequence of raw JSON strings — including malformed
or invalid ones — so boundary tests are fully deterministic with no randomness, network,
or model SDK. It structurally satisfies the ``LLMClient`` protocol.
"""

from collections.abc import Sequence

from .client import HypothesisRequest, LLMProposal


class FakeLLMClient:
    """Replay scripted raw JSON responses in order, one per request."""

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses: tuple[str, ...] = tuple(responses)
        self._index = 0

    async def propose_metric_hypotheses(self, request: HypothesisRequest) -> LLMProposal:
        if self._index >= len(self._responses):
            raise IndexError
        raw = self._responses[self._index]
        self._index += 1
        return LLMProposal(raw_json=raw)
