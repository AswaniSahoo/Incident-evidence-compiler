"""Immutable metric-shift evidence value types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..baseline import AbstentionReason, BaselinePolicy, SuspicionCandidate
from ..identifiers import EvidenceId, IncidentId, RunId, TenantId
from ..incidents import IncidentWindow
from ..metrics import SignalKey

SCHEMA_VERSION = "metric-evidence-ledger.v1"


class MetricShiftDecisionKind(StrEnum):
    """The aggregate Phase 1 decision retained as diagnostic context."""

    RANKING = "ranking"
    ABSTENTION = "abstention"


@dataclass(frozen=True, slots=True, repr=False)
class MetricShiftDecision:
    """A finite, immutable snapshot of the aggregate baseline decision."""

    kind: MetricShiftDecisionKind
    abstention_reason: AbstentionReason | None
    candidate_signal_keys: tuple[SignalKey, ...]
    eligible_signal_count: int
    top_score: float | None
    second_score: float | None
    lead: float | None

    def __repr__(self) -> str:
        return (
            f"MetricShiftDecision(kind='{self.kind.value}', "
            f"candidate_count={len(self.candidate_signal_keys)})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class MetricShiftEvidence:
    """Replayable evidence for exactly one evaluated metric signal."""

    evidence_id: EvidenceId
    signal_key: SignalKey
    pre_point_count: int
    post_point_count: int
    eligible: bool
    absolute_scale_floor: float
    relative_scale_floor: float
    candidate: SuspicionCandidate | None

    def __repr__(self) -> str:
        return f"MetricShiftEvidence(eligible={self.eligible})"


@dataclass(frozen=True, slots=True, repr=False)
class MetricEvidenceLedger:
    """One immutable Phase 1 baseline bound to an exact incident run context."""

    schema_version: str
    tenant_id: TenantId
    incident_id: IncidentId
    run_id: RunId
    window: IncidentWindow
    policy: BaselinePolicy
    decision: MetricShiftDecision
    entries: tuple[MetricShiftEvidence, ...]

    def __repr__(self) -> str:
        return (
            f"MetricEvidenceLedger(schema_version='{self.schema_version}', "
            f"entry_count={len(self.entries)}, decision='{self.decision.kind.value}')"
        )
