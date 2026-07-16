"""Nominal identifiers used by the domain."""

from dataclasses import dataclass
from uuid import UUID

from .errors import InvalidIdentifierError


def _validate_text_identifier(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidIdentifierError


@dataclass(frozen=True, slots=True)
class TenantId:
    value: str

    def __post_init__(self) -> None:
        _validate_text_identifier(self.value)


@dataclass(frozen=True, slots=True)
class IncidentId:
    value: str

    def __post_init__(self) -> None:
        _validate_text_identifier(self.value)


@dataclass(frozen=True, slots=True)
class RunId:
    value: str

    def __post_init__(self) -> None:
        _validate_text_identifier(self.value)


@dataclass(frozen=True, slots=True)
class EvidenceId:
    value: str

    def __post_init__(self) -> None:
        _validate_text_identifier(self.value)


@dataclass(frozen=True, slots=True)
class CaseId:
    value: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.value, UUID):
            raise InvalidIdentifierError

    def __str__(self) -> str:
        return str(self.value)

    def __repr__(self) -> str:
        return f"CaseId('{self.value}')"
