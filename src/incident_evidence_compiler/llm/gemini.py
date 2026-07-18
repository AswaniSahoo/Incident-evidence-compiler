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


def _unwrap_json(text: str) -> str:
    """Unwrap a markdown code fence if the model wrapped its JSON in one.

    Gemini frequently returns ```json ... ``` despite a JSON-only instruction. Unwrapping
    is provider-specific output normalization only; the result stays fully untrusted and
    must still pass ``parse_metric_hypothesis`` before any field is trusted.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _build_prompt(request: HypothesisRequest) -> str:
    signals = "\n".join(f"  - {key.value}" for key in sorted(request.allowed_signals, key=str))
    return (
        "You assist an incident investigation. Propose descriptive metric-shift hypotheses "
        "that can be verified against evidence.\n\n"
        "Return ONLY a single JSON object (no markdown fences, no prose) with exactly these "
        "fields:\n"
        '  "hypothesis_id": a short non-empty string,\n'
        f'  "tenant_id": "{request.tenant.value}",\n'
        f'  "incident_id": "{request.incident.value}",\n'
        f'  "run_id": "{request.run.value}",\n'
        '  "semantics": "descriptive",\n'
        '  "composition": "any",\n'
        '  "predicates": a JSON list of 1 to 5 objects, each exactly '
        '{"predicate_id": "<unique non-empty string>", "signal_key": "<one allowed signal>", '
        '"expected_direction": "increase" or "decrease"}.\n\n'
        "Strict rules:\n"
        "- Copy tenant_id, incident_id and run_id EXACTLY as shown above.\n"
        '- "semantics" must be exactly "descriptive".\n'
        '- "composition" must be exactly "all" or "any".\n'
        '- "expected_direction" must be exactly "increase" or "decrease" (lower case).\n'
        "- Every signal_key MUST be copied verbatim from the allowed list below; use no "
        "other names.\n"
        "- Pick the few signals most likely to show the incident's metric shift.\n\n"
        f"Allowed signal keys:\n{signals}\n"
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

        # Pin the Gemini Developer API explicitly: an API key selects that backend, and
        # passing vertexai=False prevents an ambient Vertex environment (for example a
        # GOOGLE_GENAI_USE_VERTEXAI=true / GOOGLE_CLOUD_PROJECT set by a local gcloud SDK)
        # from silently rerouting an API-key client to aiplatform.googleapis.com, which
        # rejects API keys.
        client = genai.Client(api_key=api_key, vertexai=False)
        return cls(
            _GenaiModelsAdapter(client),
            model=model,
            deadline=deadline,
            max_attempts=max_attempts,
        )

    @classmethod
    def from_vertex(
        cls,
        *,
        project: str,
        location: str,
        model: str = _DEFAULT_MODEL,
        deadline: timedelta = _DEFAULT_DEADLINE,
        max_attempts: int = 2,
    ) -> "GeminiLLMClient":
        """Build a client backed by Vertex AI using Application Default Credentials.

        The caller supplies the billing project and location explicitly; authentication is
        the ambient ADC set up by ``gcloud auth application-default login``. No API key is
        used on this path.
        """
        from google import genai

        client = genai.Client(vertexai=True, project=project, location=location)
        return cls(
            _GenaiModelsAdapter(client),
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
            raw_json=_unwrap_json(text),
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
    """Adapts a ``google-genai`` client to the ``_AsyncModels`` port.

    The whole SDK client is retained (not just ``client.aio.models``) so its lazily-created
    async HTTP transport is not garbage-collected and closed after construction — a closed
    transport otherwise fails every request with "Cannot send a request, as the client has
    been closed." The client is held as ``Any`` so all provider typing stays confined here.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    async def generate_content(self, *, model: str, contents: str) -> _GenerateResponse:
        response = await self._client.aio.models.generate_content(model=model, contents=contents)
        return cast(_GenerateResponse, response)
