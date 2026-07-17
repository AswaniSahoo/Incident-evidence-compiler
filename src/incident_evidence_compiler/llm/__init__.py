"""LLM provider boundary.

Framework-independent contracts for proposing restricted metric-shift hypotheses, a
deterministic in-memory fake, the untrusted-output parser that maps model JSON into domain
hypothesis types, and a Gemini adapter behind the same protocol. This package may import
``domain``; the domain must never import this package. No module here opens a network
connection or performs I/O at import time; the Gemini SDK is imported lazily only when a
real client is constructed.
"""

from .client import HypothesisRequest, LLMClient, LLMProposal
from .errors import (
    EmptyProposalError,
    LLMError,
    LLMValidationError,
    MalformedProposalError,
    ProposalSchemaError,
    ProposalsExhaustedError,
    ProposalTooLargeError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    TooManyPredicatesError,
    UnauthorizedEntityError,
)
from .fake import FakeLLMClient
from .gemini import GeminiLLMClient
from .parsing import MAX_PROPOSAL_CHARS, parse_metric_hypothesis

__all__ = [
    "MAX_PROPOSAL_CHARS",
    "EmptyProposalError",
    "FakeLLMClient",
    "GeminiLLMClient",
    "HypothesisRequest",
    "LLMClient",
    "LLMError",
    "LLMProposal",
    "LLMValidationError",
    "MalformedProposalError",
    "ProposalSchemaError",
    "ProposalTooLargeError",
    "ProposalsExhaustedError",
    "ProviderResponseError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "TooManyPredicatesError",
    "UnauthorizedEntityError",
    "parse_metric_hypothesis",
]
