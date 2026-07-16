"""Incident time-window contracts."""

from dataclasses import dataclass
from datetime import UTC, datetime

from .errors import InvalidIncidentWindowError, InvalidTimestampError


def to_utc(value: object) -> datetime:
    """Validate an aware datetime and canonicalize it to UTC."""
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InvalidTimestampError
    try:
        offset = value.utcoffset()
        converted = value.astimezone(UTC)
    except (OverflowError, ValueError):
        pass
    else:
        if offset is not None:
            return converted
    raise InvalidTimestampError from None


@dataclass(frozen=True, slots=True)
class IncidentWindow:
    start: datetime
    injection: datetime
    end: datetime

    def __post_init__(self) -> None:
        start = to_utc(self.start)
        injection = to_utc(self.injection)
        end = to_utc(self.end)
        if not start <= injection < end:
            raise InvalidIncidentWindowError
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "injection", injection)
        object.__setattr__(self, "end", end)
