"""Framework-independent LLM provider contracts.

The provider boundary is deliberately narrow: a request carries only the tenant, run,
and the frozen allow-list of signal keys a proposal may reference; a proposal is an
opaque JSON string plus optional model metadata. Callers depend on the ``LLMClient``
protocol rather than any concrete backend. Nothing here opens a network connection or
imports a model SDK, and the untrusted ``raw_json`` is only trustworthy once it has
passed through ``parse_metric_hypothesis``.
"""

from dataclasses import dataclass
from typing import Protocol

from ..domain.identifiers import IncidentId, RunId, TenantId
from ..domain.metrics import SignalKey


@dataclass(frozen=True, slots=True)
class HypothesisRequest:
    """A bounded, tenant-scoped request for metric-shift hypotheses."""

    tenant: TenantId
    incident: IncidentId
    run: RunId
    allowed_signals: frozenset[SignalKey]


@dataclass(frozen=True, slots=True)
class LLMProposal:
    """An untrusted proposal returned by a provider.

    ``raw_json`` is opaque model text; it must be parsed and validated through
    ``parse_metric_hypothesis`` before any field is trusted. The optional metadata is
    provenance only and never influences validation.
    """

    raw_json: str
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMClient(Protocol):
    async def propose_metric_hypotheses(self, request: HypothesisRequest) -> LLMProposal:
        """Return an untrusted proposal for the request; parse it before trusting it."""
        ...
