"""Restricted, non-executable metric-shift hypothesis contracts."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn

from .errors import InvalidHypothesisError
from .identifiers import IncidentId, RunId, TenantId
from .metrics import SignalKey


def _raise_invalid() -> NoReturn:
    raise InvalidHypothesisError


MAX_PREDICATES = 32


class HypothesisSemantics(StrEnum):
    """Whether a hypothesis is descriptive or makes an unverifiable causal claim."""

    DESCRIPTIVE = "descriptive"
    CAUSAL = "causal"


class HypothesisComposition(StrEnum):
    """Flat three-valued composition applied to all predicates."""

    ALL = "all"
    ANY = "any"


class ExpectedDirection(StrEnum):
    """The directional metric shift asserted by a predicate."""

    INCREASE = "increase"
    DECREASE = "decrease"


@dataclass(frozen=True, slots=True, repr=False)
class MetricShiftPredicate:
    """One allow-listed assertion over one exact metric signal."""

    predicate_id: str
    signal_key: SignalKey
    expected_direction: ExpectedDirection

    def __post_init__(self) -> None:
        if not isinstance(self.predicate_id, str) or not self.predicate_id.strip():
            raise InvalidHypothesisError
        if type(self.signal_key) is not SignalKey:
            raise InvalidHypothesisError
        if type(self.expected_direction) is not ExpectedDirection:
            raise InvalidHypothesisError
        try:
            signal_key = SignalKey(self.signal_key.value)
        except Exception:
            raise InvalidHypothesisError from None
        object.__setattr__(self, "signal_key", signal_key)

    def __repr__(self) -> str:
        return "MetricShiftPredicate()"


@dataclass(frozen=True, slots=True, init=False, repr=False)
class HypothesisDocument:
    """A flat, bounded hypothesis bound to one exact evidence-ledger context."""

    hypothesis_id: str
    tenant_id: TenantId
    incident_id: IncidentId
    run_id: RunId
    semantics: HypothesisSemantics
    composition: HypothesisComposition
    predicates: tuple[MetricShiftPredicate, ...]

    def __init__(
        self,
        hypothesis_id: str,
        tenant_id: TenantId,
        incident_id: IncidentId,
        run_id: RunId,
        semantics: HypothesisSemantics,
        composition: HypothesisComposition,
        predicates: Iterable[MetricShiftPredicate],
    ) -> None:
        if not isinstance(hypothesis_id, str) or not hypothesis_id.strip():
            raise InvalidHypothesisError
        try:
            if type(tenant_id) is not TenantId:
                raise InvalidHypothesisError
            if type(incident_id) is not IncidentId:
                raise InvalidHypothesisError
            if type(run_id) is not RunId:
                raise InvalidHypothesisError
            if type(semantics) is not HypothesisSemantics:
                raise InvalidHypothesisError
            if type(composition) is not HypothesisComposition:
                raise InvalidHypothesisError
            copied_tenant = TenantId(tenant_id.value)
            copied_incident = IncidentId(incident_id.value)
            copied_run = RunId(run_id.value)
            materialized = tuple(predicates)
            copied_predicates = tuple(
                MetricShiftPredicate(
                    predicate.predicate_id,
                    predicate.signal_key,
                    predicate.expected_direction,
                )
                if type(predicate) is MetricShiftPredicate
                else _raise_invalid()
                for predicate in materialized
            )
        except InvalidHypothesisError:
            raise
        except Exception:
            raise InvalidHypothesisError from None
        if not 1 <= len(copied_predicates) <= MAX_PREDICATES:
            raise InvalidHypothesisError
        predicate_ids = tuple(predicate.predicate_id for predicate in copied_predicates)
        signal_keys = tuple(predicate.signal_key.value for predicate in copied_predicates)
        if len(set(predicate_ids)) != len(predicate_ids):
            raise InvalidHypothesisError
        if len(set(signal_keys)) != len(signal_keys):
            raise InvalidHypothesisError

        object.__setattr__(self, "hypothesis_id", hypothesis_id)
        object.__setattr__(self, "tenant_id", copied_tenant)
        object.__setattr__(self, "incident_id", copied_incident)
        object.__setattr__(self, "run_id", copied_run)
        object.__setattr__(self, "semantics", semantics)
        object.__setattr__(self, "composition", composition)
        object.__setattr__(self, "predicates", copied_predicates)

    def __repr__(self) -> str:
        return f"HypothesisDocument(predicate_count={len(self.predicates)})"


def validate_hypothesis_document(value: object) -> HypothesisDocument:
    """Return a deeply reconstructed hypothesis or raise one stable domain error."""
    if type(value) is not HypothesisDocument:
        raise InvalidHypothesisError
    try:
        return HypothesisDocument(
            value.hypothesis_id,
            value.tenant_id,
            value.incident_id,
            value.run_id,
            value.semantics,
            value.composition,
            value.predicates,
        )
    except InvalidHypothesisError:
        raise
    except Exception:
        raise InvalidHypothesisError from None
