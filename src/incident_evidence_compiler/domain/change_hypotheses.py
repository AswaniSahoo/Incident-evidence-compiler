"""Restricted, non-executable change co-occurrence hypothesis contracts.

A change hypothesis asserts only descriptive temporal co-occurrence: that a
change of an exact kind to an exact target occurred in a bounded temporal region
of the incident window. It reuses the Phase 2 semantics and composition enums so
the causal gate and three-valued composition stay identical. There is no free
text, wildcard, negation, nesting, threshold, or executable field.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn

from .changes import ChangeEventKey, ChangeKind
from .errors import InvalidChangeHypothesisError
from .hypotheses import HypothesisComposition, HypothesisSemantics
from .identifiers import IncidentId, RunId, TenantId

MAX_CHANGE_PREDICATES = 32


def _raise_invalid() -> NoReturn:
    raise InvalidChangeHypothesisError


class ChangePhaseConstraint(StrEnum):
    """The temporal region a co-occurrence predicate asserts a change occupies."""

    WITHIN_WINDOW = "within_window"
    PRE_INJECTION = "pre_injection"
    POST_INJECTION = "post_injection"


@dataclass(frozen=True, slots=True, repr=False)
class ChangeCooccurrencePredicate:
    """One allow-listed assertion over one exact change target, kind, and phase."""

    predicate_id: str
    event_key: ChangeEventKey
    kind: ChangeKind
    phase_constraint: ChangePhaseConstraint

    def __post_init__(self) -> None:
        if not isinstance(self.predicate_id, str) or not self.predicate_id.strip():
            raise InvalidChangeHypothesisError
        if type(self.event_key) is not ChangeEventKey:
            raise InvalidChangeHypothesisError
        if type(self.kind) is not ChangeKind:
            raise InvalidChangeHypothesisError
        if type(self.phase_constraint) is not ChangePhaseConstraint:
            raise InvalidChangeHypothesisError
        try:
            event_key = ChangeEventKey(self.event_key.value)
        except Exception:
            raise InvalidChangeHypothesisError from None
        object.__setattr__(self, "event_key", event_key)

    def __repr__(self) -> str:
        return "ChangeCooccurrencePredicate()"


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ChangeHypothesisDocument:
    """A flat, bounded change hypothesis bound to one exact ledger context."""

    hypothesis_id: str
    tenant_id: TenantId
    incident_id: IncidentId
    run_id: RunId
    semantics: HypothesisSemantics
    composition: HypothesisComposition
    predicates: tuple[ChangeCooccurrencePredicate, ...]

    def __init__(
        self,
        hypothesis_id: str,
        tenant_id: TenantId,
        incident_id: IncidentId,
        run_id: RunId,
        semantics: HypothesisSemantics,
        composition: HypothesisComposition,
        predicates: Iterable[ChangeCooccurrencePredicate],
    ) -> None:
        if not isinstance(hypothesis_id, str) or not hypothesis_id.strip():
            raise InvalidChangeHypothesisError
        try:
            if type(tenant_id) is not TenantId:
                raise InvalidChangeHypothesisError
            if type(incident_id) is not IncidentId:
                raise InvalidChangeHypothesisError
            if type(run_id) is not RunId:
                raise InvalidChangeHypothesisError
            if type(semantics) is not HypothesisSemantics:
                raise InvalidChangeHypothesisError
            if type(composition) is not HypothesisComposition:
                raise InvalidChangeHypothesisError
            copied_tenant = TenantId(tenant_id.value)
            copied_incident = IncidentId(incident_id.value)
            copied_run = RunId(run_id.value)
            materialized = tuple(predicates)
            copied_predicates = tuple(
                ChangeCooccurrencePredicate(
                    predicate.predicate_id,
                    predicate.event_key,
                    predicate.kind,
                    predicate.phase_constraint,
                )
                if type(predicate) is ChangeCooccurrencePredicate
                else _raise_invalid()
                for predicate in materialized
            )
        except InvalidChangeHypothesisError:
            raise
        except Exception:
            raise InvalidChangeHypothesisError from None
        if not 1 <= len(copied_predicates) <= MAX_CHANGE_PREDICATES:
            raise InvalidChangeHypothesisError
        predicate_ids = tuple(predicate.predicate_id for predicate in copied_predicates)
        if len(set(predicate_ids)) != len(predicate_ids):
            raise InvalidChangeHypothesisError

        object.__setattr__(self, "hypothesis_id", hypothesis_id)
        object.__setattr__(self, "tenant_id", copied_tenant)
        object.__setattr__(self, "incident_id", copied_incident)
        object.__setattr__(self, "run_id", copied_run)
        object.__setattr__(self, "semantics", semantics)
        object.__setattr__(self, "composition", composition)
        object.__setattr__(self, "predicates", copied_predicates)

    def __repr__(self) -> str:
        return f"ChangeHypothesisDocument(predicate_count={len(self.predicates)})"


def validate_change_hypothesis_document(value: object) -> ChangeHypothesisDocument:
    """Return a deeply reconstructed change hypothesis or one stable error."""
    if type(value) is not ChangeHypothesisDocument:
        raise InvalidChangeHypothesisError
    try:
        return ChangeHypothesisDocument(
            value.hypothesis_id,
            value.tenant_id,
            value.incident_id,
            value.run_id,
            value.semantics,
            value.composition,
            value.predicates,
        )
    except InvalidChangeHypothesisError:
        raise
    except Exception:
        raise InvalidChangeHypothesisError from None
