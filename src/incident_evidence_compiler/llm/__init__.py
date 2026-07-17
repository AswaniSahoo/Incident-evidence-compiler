"""LLM provider boundary.

Framework-independent contracts for proposing restricted metric-shift hypotheses, a
deterministic in-memory fake, and the untrusted-output parser that maps model JSON into
domain hypothesis types. This package may import ``domain``; the domain must never import
this package. No module here opens a network connection, imports a model SDK, or performs
I/O at import time; a concrete, dependency-gated provider adapter arrives in a later slice.
"""

from .client import HypothesisRequest, LLMClient, LLMProposal
from .errors import (
    EmptyProposalError,
    LLMError,
    LLMValidationError,
    MalformedProposalError,
    ProposalSchemaError,
    ProposalTooLargeError,
    TooManyPredicatesError,
    UnauthorizedEntityError,
)
from .fake import FakeLLMClient
from .parsing import MAX_PROPOSAL_CHARS, parse_metric_hypothesis

__all__ = [
    "MAX_PROPOSAL_CHARS",
    "EmptyProposalError",
    "FakeLLMClient",
    "HypothesisRequest",
    "LLMClient",
    "LLMError",
    "LLMProposal",
    "LLMValidationError",
    "MalformedProposalError",
    "ProposalSchemaError",
    "ProposalTooLargeError",
    "TooManyPredicatesError",
    "UnauthorizedEntityError",
    "parse_metric_hypothesis",
]
