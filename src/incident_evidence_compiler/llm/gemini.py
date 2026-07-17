"""Async Gemini provider implementing the LLM boundary.

The client depends on a narrow injected port (``_AsyncModels``) rather than the
``google-genai`` SDK directly, so it is unit-testable without a network and the SDK
coupling is confined to one adapter with a single ``Any`` seam. The SDK is imported
lazily inside ``from_api_key`` — importing this module opens no network and needs no
credentials.

Operational behavior: each attempt is bounded by a deadline; a transient failure is
retried once; a timeout, an exhausted retry, or a malformed/empty response each surface a
stable, message-free provider error. The returned ``raw_json`` is still untrusted and must
be validated through ``parse_metric_hypothesis``.
"""

import asyncio
from datetime import timedelta
from typing import Any, Protocol, cast

from .client import HypothesisRequest, LLMProposal
from .errors import ProviderResponseError, ProviderTimeoutError, ProviderUnavailableError

_DEFAULT_MODEL = "gemini-2.0-flash"
_DEFAULT_DEADLINE = timedelta(seconds=30)


class _GenerateResponse(Protocol):
    text: str | None


class _AsyncModels(Protocol):
    async def generate_content(self, *, model: str, contents: str) -> _GenerateResponse: ...


def _token_count(usage: object, name: str) -> int | None:
    value = getattr(usage, name, None)
    return value if isinstance(value, int) else None


def _build_prompt(request: HypothesisRequest) -> str:
    signals = ", ".join(sorted(key.value for key in request.allowed_signals))
    return (
        "Propose restricted metric-shift hypotheses for an incident investigation.\n"
        f"Tenant: {request.tenant.value}\n"
        f"Run: {request.run.value}\n"
        f"You may reference only these signal keys: {signals}\n"
        "Return a single JSON object with fields hypothesis_id, tenant_id, incident_id, "
        "run_id, semantics, composition, and predicates (a list of objects each with "
        "predicate_id, signal_key, expected_direction). Return JSON only, no prose."
    )


class GeminiLLMClient:
    """An ``LLMClient`` backed by Gemini through an injected async models port."""

    def __init__(
        self,
        models: _AsyncModels,
        *,
        model: str = _DEFAULT_MODEL,
        deadline: timedelta = _DEFAULT_DEADLINE,
        max_attempts: int = 2,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._models = models
        self._model = model
        self._deadline = deadline
        self._max_attempts = max_attempts

    @classmethod
    def from_api_key(
        cls,
        api_key: str,
        *,
        model: str = _DEFAULT_MODEL,
        deadline: timedelta = _DEFAULT_DEADLINE,
        max_attempts: int = 2,
    ) -> "GeminiLLMClient":
        """Build a client backed by the real ``google-genai`` async SDK."""
        from google import genai

        client = genai.Client(api_key=api_key)
        return cls(
            _GenaiModelsAdapter(client.aio.models),
            model=model,
            deadline=deadline,
            max_attempts=max_attempts,
        )

    async def propose_metric_hypotheses(self, request: HypothesisRequest) -> LLMProposal:
        response = await self._generate(_build_prompt(request))
        text = response.text
        if text is None or not text.strip():
            raise ProviderResponseError
        usage = getattr(response, "usage_metadata", None)
        return LLMProposal(
            raw_json=text,
            model=self._model,
            prompt_tokens=_token_count(usage, "prompt_token_count"),
            completion_tokens=_token_count(usage, "candidates_token_count"),
        )

    async def _generate(self, prompt: str) -> _GenerateResponse:
        timeout_seconds = self._deadline.total_seconds()
        for attempt in range(1, self._max_attempts + 1):
            try:
                async with asyncio.timeout(timeout_seconds):
                    return await self._models.generate_content(model=self._model, contents=prompt)
            except TimeoutError:
                raise ProviderTimeoutError from None
            except Exception:
                if attempt >= self._max_attempts:
                    raise ProviderUnavailableError from None
        raise ProviderUnavailableError


class _GenaiModelsAdapter:
    """Adapts the ``google-genai`` async models object to the ``_AsyncModels`` port.

    The SDK object is held as ``Any`` so all provider typing stays confined here.
    """

    def __init__(self, models: Any) -> None:
        self._models = models

    async def generate_content(self, *, model: str, contents: str) -> _GenerateResponse:
        response = await self._models.generate_content(model=model, contents=contents)
        return cast(_GenerateResponse, response)
