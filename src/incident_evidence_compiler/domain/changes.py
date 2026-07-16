"""Bounded, immutable change-event telemetry contracts.

A change event is a discrete, typed, timestamped occurrence (a deployment,
configuration change, rollback, scaling action, or feature-flag flip). It is raw
telemetry and therefore untrusted: the contract validates and canonicalizes it
but never interprets it or asserts that it caused anything.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .errors import InvalidChangeEventError
from .incidents import to_utc

# A conservative cap that keeps a single incident's change log bounded and
# replayable. The value is a contract, not a tuning knob.
MAX_CHANGE_EVENTS = 512


class ChangeKind(StrEnum):
    """The closed set of recognized operational change categories."""

    DEPLOYMENT = "deployment"
    CONFIGURATION = "configuration"
    ROLLBACK = "rollback"
    SCALING = "scaling"
    FEATURE_FLAG = "feature_flag"


@dataclass(frozen=True, slots=True)
class ChangeEventKey:
    """An opaque key identifying the changed component.

    It is deliberately opaque telemetry, never a human service or fault label.
    """

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise InvalidChangeEventError


@dataclass(frozen=True, slots=True)
class ChangeEvent:
    """One discrete change occurrence with an aware UTC timestamp."""

    event_key: ChangeEventKey
    kind: ChangeKind
    occurred_at: datetime

    def __post_init__(self) -> None:
        if type(self.event_key) is not ChangeEventKey:
            raise InvalidChangeEventError
        if type(self.kind) is not ChangeKind:
            raise InvalidChangeEventError
        object.__setattr__(self, "occurred_at", to_utc(self.occurred_at))


@dataclass(frozen=True, slots=True, init=False)
class ChangeEventLog:
    """A bounded, canonically ordered, duplicate-free set of change events.

    An empty log is valid: it records that no change events were observed, which
    is distinct from a missing observation. Events are ordered deterministically
    by ``(occurred_at, kind, event_key)``. Two events sharing all three fields
    are indistinguishable and rejected; the contract never invents deduplication
    or repair semantics.
    """

    events: tuple[ChangeEvent, ...]

    def __init__(self, events: Iterable[ChangeEvent]) -> None:
        materialized = tuple(events)
        if len(materialized) > MAX_CHANGE_EVENTS:
            raise InvalidChangeEventError
        if not all(type(event) is ChangeEvent for event in materialized):
            raise InvalidChangeEventError
        seen: set[tuple[str, str, datetime]] = set()
        for event in materialized:
            identity = (event.event_key.value, event.kind.value, event.occurred_at)
            if identity in seen:
                raise InvalidChangeEventError
            seen.add(identity)
        ordered = tuple(
            sorted(
                materialized,
                key=lambda event: (event.occurred_at, event.kind.value, event.event_key.value),
            )
        )
        object.__setattr__(self, "events", ordered)
