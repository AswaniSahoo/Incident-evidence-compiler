"""Parse untrusted model output into a restricted hypothesis document.

Everything crossing this function is untrusted: it enforces a hard input-size ceiling,
rejects empty text, parses JSON defensively, requires a JSON object, delegates deep
structural validation to the domain, and finally enforces the caller's signal allow-list
and predicate budget. Every rejection raises a stable, message-free ``LLMValidationError``
subclass so no model text or tenant value ever leaks across the boundary.
"""

import json

from ..domain.hypotheses import (
    MAX_PREDICATES,
    ExpectedDirection,
    HypothesisComposition,
    HypothesisDocument,
    HypothesisSemantics,
    MetricShiftPredicate,
    validate_hypothesis_document,
)
from ..domain.identifiers import IncidentId, RunId, TenantId
from ..domain.metrics import SignalKey
from .errors import (
    EmptyProposalError,
    MalformedProposalError,
    ProposalSchemaError,
    ProposalTooLargeError,
    TooManyPredicatesError,
    UnauthorizedEntityError,
)

# Hard ceiling on untrusted input length, checked before any parsing work is attempted.
MAX_PROPOSAL_CHARS = 65_536


def parse_metric_hypothesis(
    raw: str, *, allowed_signals: frozenset[SignalKey]
) -> HypothesisDocument:
    """Return a validated ``HypothesisDocument`` or raise a stable LLM error.

    The ``raw`` string is treated as fully untrusted model output. On any rejection a
    message-free ``LLMValidationError`` subclass is raised with its cause suppressed
    (``from None``), so no model-derived text is retained anywhere in the exception.
    """
    if len(raw) > MAX_PROPOSAL_CHARS:
        raise ProposalTooLargeError
    if not raw.strip():
        raise EmptyProposalError
    try:
        parsed = json.loads(raw)
    except (RecursionError, json.JSONDecodeError):
        raise MalformedProposalError from None
    if not isinstance(parsed, dict):
        raise ProposalSchemaError
    predicates = parsed.get("predicates")
    if not isinstance(predicates, list):
        raise ProposalSchemaError
    if len(predicates) > MAX_PREDICATES:
        raise TooManyPredicatesError
    try:
        predicate_objects = tuple(_build_predicate(entry) for entry in predicates)
        document = validate_hypothesis_document(
            HypothesisDocument(
                parsed["hypothesis_id"],
                TenantId(parsed["tenant_id"]),
                IncidentId(parsed["incident_id"]),
                RunId(parsed["run_id"]),
                HypothesisSemantics(parsed["semantics"]),
                HypothesisComposition(parsed["composition"]),
                predicate_objects,
            )
        )
    except (KeyError, TypeError, ValueError):
        raise ProposalSchemaError from None
    for predicate in document.predicates:
        if predicate.signal_key not in allowed_signals:
            raise UnauthorizedEntityError
    return document


def _build_predicate(entry: object) -> MetricShiftPredicate:
    """Map one untrusted predicate object into a domain predicate.

    Raises a plain ``TypeError`` for a non-object entry; the caller maps every structural
    rejection to ``ProposalSchemaError``.
    """
    if not isinstance(entry, dict):
        raise TypeError
    return MetricShiftPredicate(
        entry["predicate_id"],
        SignalKey(entry["signal_key"]),
        ExpectedDirection(entry["expected_direction"]),
    )
