"""Typed, sanitized LLM-boundary failures.

These mirror the domain and persistence error convention: a stable ``code`` class
variable and no free-form message, so a failure crossing the boundary never leaks model
text, tenant data, or proposal payloads.
"""

from typing import ClassVar


class LLMError(Exception):
    """Base class for stable LLM-boundary errors."""

    code: ClassVar[str] = "llm_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class LLMValidationError(LLMError, ValueError):
    """Base class for rejected, untrusted model output."""


class MalformedProposalError(LLMValidationError):
    code = "malformed_proposal"


class EmptyProposalError(LLMValidationError):
    code = "empty_proposal"


class ProposalSchemaError(LLMValidationError):
    code = "proposal_schema_invalid"


class UnauthorizedEntityError(LLMValidationError):
    code = "unauthorized_entity"


class TooManyPredicatesError(LLMValidationError):
    code = "too_many_predicates"


class ProposalTooLargeError(LLMValidationError):
    code = "proposal_too_large"


# Operational provider failures (not input-validation): these are LLMError but not
# LLMValidationError, since they describe a provider outcome rather than bad model output.
class ProviderTimeoutError(LLMError):
    code = "provider_timeout"


class ProviderUnavailableError(LLMError):
    code = "provider_unavailable"


class ProviderResponseError(LLMError):
    code = "provider_response_invalid"


class ProposalsExhaustedError(LLMError):
    """A test double ran out of scripted proposals (harness misconfiguration)."""

    code = "proposals_exhausted"
