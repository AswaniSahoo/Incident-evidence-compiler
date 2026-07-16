"""End-to-end bounded RCAEval evaluation adapter."""

from dataclasses import dataclass
from pathlib import Path

from incident_evidence_compiler.domain import CaseId, IncidentWindow, MetricSignal

from .csv_loader import parse_case
from .discovery import discover_cases, validate_root
from .errors import LoadErrorCode, RcaevalLoadError
from .ids import (
    CaseIdFactory,
    RcaevalSplit,
    SealedSplitPermit,
    guard_split,
    parse_split,
    random_case_id,
    unique_case_id,
)
from .limits import LoaderLimits
from .sidecar import EvaluationSidecar, SidecarEntry, persist_sidecar


@dataclass(frozen=True, slots=True, repr=False)
class InvestigationCase:
    case_id: CaseId
    split: RcaevalSplit
    window: IncidentWindow
    signals: tuple[MetricSignal, ...]

    def __repr__(self) -> str:
        return (
            f"InvestigationCase(case_id={self.case_id!r}, split='{self.split}', "
            f"signal_count={len(self.signals)})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class EvaluationBatch:
    cases: tuple[InvestigationCase, ...]
    sidecar: EvaluationSidecar

    def __repr__(self) -> str:
        return f"EvaluationBatch(case_count={len(self.cases)})"


class RcaevalAdapter:
    """Load an already extracted local split with no network or archive behavior."""

    def __init__(
        self,
        *,
        limits: LoaderLimits | None = None,
        case_id_factory: CaseIdFactory = random_case_id,
    ) -> None:
        self._limits = limits if limits is not None else LoaderLimits()
        self._case_id_factory = case_id_factory

    def __repr__(self) -> str:
        return "RcaevalAdapter(bounded=True)"

    def load(
        self,
        root: Path,
        split: object,
        *,
        sealed_permit: SealedSplitPermit | None = None,
        replay_destination: Path | None = None,
        sidecar_root: Path | None = None,
    ) -> EvaluationBatch:
        try:
            return self._load(
                root,
                split,
                sealed_permit=sealed_permit,
                replay_destination=replay_destination,
                sidecar_root=sidecar_root,
            )
        except RcaevalLoadError as error:
            code = error.code
            case_id = error.case_id
        raise RcaevalLoadError(code, case_id) from None

    def _load(
        self,
        root: Path,
        split: object,
        *,
        sealed_permit: SealedSplitPermit | None = None,
        replay_destination: Path | None = None,
        sidecar_root: Path | None = None,
    ) -> EvaluationBatch:
        parsed_split = parse_split(split)
        guard_split(parsed_split, sealed_permit)
        validate_root(root, parsed_split)
        discovered = discover_cases(root, self._limits)
        assigned: set[CaseId] = set()
        cases: list[InvestigationCase] = []
        entries: list[SidecarEntry] = []
        for source in discovered:
            case_id = unique_case_id(self._case_id_factory, assigned)
            parsed = parse_case(source, case_id, self._limits)
            cases.append(InvestigationCase(case_id, parsed_split, parsed.window, parsed.signals))
            entries.append(
                SidecarEntry(
                    case_id=case_id,
                    split=parsed_split,
                    source_locator=source.source_locator,
                    root_cause_service=source.root_cause_service,
                    injected_fault_type=source.injected_fault_type,
                    repetition=source.repetition,
                    answer_labels=(source.root_cause_service, source.injected_fault_type),
                )
            )
        sidecar = EvaluationSidecar(
            manifest_release="1.2.0",
            manifest_commit="bc49dbd85bd14032101fb9a69a5a37e9d6d55178",
            entries=tuple(entries),
        )
        if replay_destination is not None:
            if sidecar_root is None:
                raise RcaevalLoadError(LoadErrorCode.SIDECAR_WRITE_FAILED) from None
            persist_sidecar(sidecar, replay_destination, sidecar_root=sidecar_root)
        return EvaluationBatch(tuple(cases), sidecar)
