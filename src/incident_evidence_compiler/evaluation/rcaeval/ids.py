"""Split authorization and opaque random case identifiers."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from incident_evidence_compiler.domain import CaseId

from .errors import LoadErrorCode, RcaevalLoadError


class RcaevalSplit(StrEnum):
    OB = "OB"
    SS = "SS"
    TT = "TT"


_PERMIT_TOKEN = object()


@dataclass(frozen=True, slots=True, repr=False)
class SealedSplitPermit:
    _token: object
    _reason: str

    def __repr__(self) -> str:
        return "SealedSplitPermit(authorized=True)"


def authorize_sealed_split(*, confirmed: bool, reason: str) -> SealedSplitPermit:
    if confirmed is not True or not isinstance(reason, str) or not reason.strip():
        raise RcaevalLoadError(LoadErrorCode.SEALED_SPLIT_DENIED) from None
    return SealedSplitPermit(_PERMIT_TOKEN, reason)


def parse_split(value: object) -> RcaevalSplit:
    if not isinstance(value, str):
        raise RcaevalLoadError(LoadErrorCode.INVALID_SPLIT) from None
    try:
        return RcaevalSplit(value)
    except (TypeError, ValueError):
        raise RcaevalLoadError(LoadErrorCode.INVALID_SPLIT) from None


def guard_split(split: RcaevalSplit, permit: SealedSplitPermit | None) -> None:
    if split is RcaevalSplit.SS:
        raise RcaevalLoadError(LoadErrorCode.SPLIT_RESERVED) from None
    if split is RcaevalSplit.TT and (
        permit is None
        or not isinstance(permit, SealedSplitPermit)
        or permit._token is not _PERMIT_TOKEN
    ):
        raise RcaevalLoadError(LoadErrorCode.SEALED_SPLIT_DENIED) from None


CaseIdFactory = Callable[[], CaseId]


def random_case_id() -> CaseId:
    return CaseId(uuid4())


def unique_case_id(
    factory: CaseIdFactory,
    assigned: set[CaseId],
    *,
    attempts: int = 8,
) -> CaseId:
    for _ in range(attempts):
        try:
            case_id = factory()
        except Exception:
            raise RcaevalLoadError(LoadErrorCode.INVALID_CASE_ID) from None
        if not isinstance(case_id, CaseId) or case_id.value.version != 4:
            raise RcaevalLoadError(LoadErrorCode.INVALID_CASE_ID) from None
        if case_id not in assigned:
            assigned.add(case_id)
            return case_id
    raise RcaevalLoadError(LoadErrorCode.CASE_ID_COLLISION) from None
