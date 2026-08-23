"""Tests for the Gemini LLM client.

Hermetic by construction: the client depends on an injected async models port, so retry,
timeout, token capture, and malformed-response handling are exercised with in-process
stubs and no network. A live smoke test is gated on GEMINI_API_KEY and skipped otherwise,
so the CI gate needs no credentials.
"""

import asyncio
import os
import unittest
from datetime import timedelta

from incident_evidence_compiler.domain.identifiers import IncidentId, RunId, TenantId
from incident_evidence_compiler.domain.metrics import SignalKey
from incident_evidence_compiler.llm import (
    GeminiLLMClient,
    HypothesisRequest,
    LLMProposal,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


def _request() -> HypothesisRequest:
    return HypothesisRequest(
        tenant=TenantId("tenant-a"),
        incident=IncidentId("inc-1"),
        run=RunId("run-1"),
        allowed_signals=frozenset({SignalKey("checkoutservice_cpu")}),
    )


class _StubUsage:
    def __init__(self, prompt: int, candidates: int) -> None:
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates


class _StubResponse:
    def __init__(self, text: str | None, *, usage: object | None = None) -> None:
        self.text = text
        self.usage_metadata = usage


class _StubModels:
    def __init__(
        self,
        *,
        response: _StubResponse | None = None,
        error: Exception | None = None,
        fail_times: int = 0,
        delay: float = 0.0,
    ) -> None:
        self._response = response
        self._error = error
        self._fail_times = fail_times
        self._delay = delay
        self.calls = 0

    async def generate_content(self, *, model: str, contents: str) -> _StubResponse:
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None and self.calls <= self._fail_times:
            raise self._error
        assert self._response is not None
        return self._response


class GeminiLLMClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_returns_proposal_with_token_metadata(self) -> None:
        stub = _StubModels(response=_StubResponse('{"predicates": []}', usage=_StubUsage(11, 22)))
        client = GeminiLLMClient(stub, model="gemini-test", deadline=timedelta(seconds=5))
        proposal = await client.propose_metric_hypotheses(_request())
        self.assertEqual(proposal.raw_json, '{"predicates": []}')
        self.assertEqual(proposal.model, "gemini-test")
        self.assertEqual(proposal.prompt_tokens, 11)
        self.assertEqual(proposal.completion_tokens, 22)

    async def test_empty_text_raises_provider_response_error(self) -> None:
        client = GeminiLLMClient(
            _StubModels(response=_StubResponse("   ")), deadline=timedelta(seconds=5)
        )
        with self.assertRaises(ProviderResponseError):
            await client.propose_metric_hypotheses(_request())

    async def test_none_text_raises_provider_response_error(self) -> None:
        client = GeminiLLMClient(
            _StubModels(response=_StubResponse(None)), deadline=timedelta(seconds=5)
        )
        with self.assertRaises(ProviderResponseError):
            await client.propose_metric_hypotheses(_request())

    async def test_transient_failure_is_retried_once_then_succeeds(self) -> None:
        stub = _StubModels(
            response=_StubResponse('{"predicates": []}'),
            error=RuntimeError("transient"),
            fail_times=1,
        )
        client = GeminiLLMClient(stub, deadline=timedelta(seconds=5), max_attempts=2)
        proposal = await client.propose_metric_hypotheses(_request())
        self.assertEqual(proposal.raw_json, '{"predicates": []}')
        self.assertEqual(stub.calls, 2)

    async def test_exhausted_retries_raise_provider_unavailable(self) -> None:
        stub = _StubModels(error=RuntimeError("down"), fail_times=99)
        client = GeminiLLMClient(stub, deadline=timedelta(seconds=5), max_attempts=2)
        with self.assertRaises(ProviderUnavailableError):
            await client.propose_metric_hypotheses(_request())
        self.assertEqual(stub.calls, 2)

    async def test_deadline_exceeded_raises_provider_timeout(self) -> None:
        stub = _StubModels(response=_StubResponse('{"predicates": []}'), delay=1.0)
        client = GeminiLLMClient(stub, deadline=timedelta(seconds=0.01), max_attempts=2)
        with self.assertRaises(ProviderTimeoutError):
            await client.propose_metric_hypotheses(_request())

    def test_rejects_non_positive_max_attempts(self) -> None:
        with self.assertRaises(ValueError):
            GeminiLLMClient(_StubModels(), max_attempts=0)


class UnwrapJsonTests(unittest.TestCase):
    def test_unwraps_markdown_fenced_json(self) -> None:
        from incident_evidence_compiler.llm.gemini import _unwrap_json

        self.assertEqual(_unwrap_json('```json\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(_unwrap_json('```\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(_unwrap_json('{"a": 1}'), '{"a": 1}')
        self.assertEqual(_unwrap_json('   {"a": 1}   '), '{"a": 1}')


class GeminiFencedResponseTest(unittest.IsolatedAsyncioTestCase):
    async def test_fenced_json_response_is_unwrapped_before_return(self) -> None:
        stub = _StubModels(response=_StubResponse('```json\n{"predicates": []}\n```'))
        client = GeminiLLMClient(stub, model="gemini-test", deadline=timedelta(seconds=5))
        proposal = await client.propose_metric_hypotheses(_request())
        self.assertEqual(proposal.raw_json, '{"predicates": []}')


class GeminiDefaultModelTest(unittest.TestCase):
    """The client's default model must not drift from the configured one (regression guard).

    A retired default (e.g. ``gemini-2.0-flash``) 404s at request time but is masked whenever a
    caller passes a model explicitly; only a caller relying on the default — like the live smoke
    test below — is bitten. Pinning the two defaults to one value stops them diverging again.
    """

    def test_client_default_matches_the_configured_default(self) -> None:
        from incident_evidence_compiler.llm import gemini
        from incident_evidence_compiler.runtime import config

        self.assertEqual(gemini._DEFAULT_MODEL, config._DEFAULT_MODEL)


@unittest.skipUnless(_GEMINI_API_KEY, "requires GEMINI_API_KEY for a live Gemini smoke test")
class GeminiLiveSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_live_call_returns_a_proposal(self) -> None:
        assert _GEMINI_API_KEY is not None
        client = GeminiLLMClient.from_api_key(_GEMINI_API_KEY, deadline=timedelta(seconds=30))
        proposal = await client.propose_metric_hypotheses(_request())
        self.assertIsInstance(proposal, LLMProposal)
        self.assertTrue(proposal.raw_json.strip())


if __name__ == "__main__":
    unittest.main()
