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
