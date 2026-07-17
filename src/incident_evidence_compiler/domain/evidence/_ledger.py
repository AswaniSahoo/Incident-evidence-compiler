"""Ledger orchestration and the public compile/validate entry points."""

from __future__ import annotations

from ..baseline import (
    BaselineAbstention,
    BaselineRanking,
    BaselineResult,
    SignalEvaluation,
)
from ..errors import InvalidEvidenceLedgerError
from ..identifiers import EvidenceId, IncidentId, RunId, TenantId
from ..incidents import IncidentWindow
from ._decisions import _decision, _ledger_decision
from ._identity import _entry_payload, _evidence_id, _evidence_identifier
from ._parsing import (
    _candidate,
    _count,
    _evaluations,
    _finite_float,
    _identifier,
    _invalid,
    _policy,
    _signal_key,
    _window,
)
from .types import SCHEMA_VERSION, MetricEvidenceLedger, MetricShiftEvidence


def _validated_metric_evidence_ledger(value: object) -> MetricEvidenceLedger:
    if type(value) is not MetricEvidenceLedger or value.schema_version != SCHEMA_VERSION:
        _invalid()
    tenant = _identifier(value.tenant_id, TenantId)
    incident = _identifier(value.incident_id, IncidentId)
    run = _identifier(value.run_id, RunId)
    normalized_window = _window(value.window)
    policy = _policy(value.policy)
    if not isinstance(value.entries, tuple):
        _invalid()

    supplied_ids: list[EvidenceId] = []
    evaluations: list[SignalEvaluation] = []
    supplied_order: list[str] = []
    for entry in value.entries:
        if type(entry) is not MetricShiftEvidence:
            _invalid()
        evidence_id = _evidence_identifier(entry.evidence_id)
        signal_key = _signal_key(entry.signal_key)
        pre_count = _count(entry.pre_point_count)
        post_count = _count(entry.post_point_count)
        if type(entry.eligible) is not bool:
            _invalid()
        absolute_floor = _finite_float(entry.absolute_scale_floor, positive=True)
        relative_floor = _finite_float(entry.relative_scale_floor, nonnegative=True)
        expected_eligible = (
            pre_count >= policy.minimum_points_per_window
            and post_count >= policy.minimum_points_per_window
        )
        if (
            relative_floor != policy.relative_scale_floor
            or entry.eligible != expected_eligible
            or (entry.candidate is not None) != entry.eligible
        ):
            _invalid()
        shell = SignalEvaluation(
            signal_key=signal_key,
            absolute_scale_floor=absolute_floor,
            pre_point_count=pre_count,
            post_point_count=post_count,
            eligible=entry.eligible,
            candidate=None,
        )
        candidate = _candidate(entry.candidate, shell, policy) if entry.eligible else None
        evaluations.append(
            SignalEvaluation(
                signal_key=signal_key,
                absolute_scale_floor=absolute_floor,
                pre_point_count=pre_count,
                post_point_count=post_count,
                eligible=entry.eligible,
                candidate=candidate,
            )
        )
        supplied_ids.append(evidence_id)
        supplied_order.append(signal_key.value)

    ordered_evaluations, candidates = _evaluations(tuple(evaluations), policy)
    if supplied_order != [evaluation.signal_key.value for evaluation in ordered_evaluations]:
        _invalid()
    decision = _ledger_decision(value.decision, policy, candidates)
    entries = tuple(
        MetricShiftEvidence(
            evidence_id=_evidence_id(
                _entry_payload(
                    tenant,
                    incident,
                    run,
                    normalized_window,
                    policy,
                    decision,
                    evaluation,
                )
            ),
            signal_key=evaluation.signal_key,
            pre_point_count=evaluation.pre_point_count,
            post_point_count=evaluation.post_point_count,
            eligible=evaluation.eligible,
            absolute_scale_floor=evaluation.absolute_scale_floor,
            relative_scale_floor=policy.relative_scale_floor,
            candidate=evaluation.candidate,
        )
        for evaluation in ordered_evaluations
    )
    if tuple(entry.evidence_id for entry in entries) != tuple(supplied_ids):
        _invalid()
    return MetricEvidenceLedger(
        schema_version=SCHEMA_VERSION,
        tenant_id=tenant,
        incident_id=incident,
        run_id=run,
        window=normalized_window,
        policy=policy,
        decision=decision,
        entries=entries,
    )


def validate_metric_evidence_ledger(value: object) -> MetricEvidenceLedger:
    """Deeply reconstruct a ledger and verify every content-bound evidence ID."""
    try:
        return _validated_metric_evidence_ledger(value)
    except InvalidEvidenceLedgerError:
        raise
    except Exception:
        raise InvalidEvidenceLedgerError from None


def _compile_metric_shift_ledger(
    tenant_id: TenantId,
    incident_id: IncidentId,
    run_id: RunId,
    window: IncidentWindow,
    baseline_result: BaselineResult,
) -> MetricEvidenceLedger:
    """Validate and bind a Phase 1 result without repairing forged state."""
    tenant = _identifier(tenant_id, TenantId)
    incident = _identifier(incident_id, IncidentId)
    run = _identifier(run_id, RunId)
    normalized_window = _window(window)
    if not isinstance(baseline_result, (BaselineRanking, BaselineAbstention)):
        _invalid()
    frozen_policy = _policy(baseline_result.policy)
    evaluations, candidates = _evaluations(
        baseline_result.signal_evaluations,
        frozen_policy,
    )
    decision = _decision(baseline_result, frozen_policy, candidates)
    entries = tuple(
        MetricShiftEvidence(
            evidence_id=_evidence_id(
                _entry_payload(
                    tenant,
                    incident,
                    run,
                    normalized_window,
                    frozen_policy,
                    decision,
                    evaluation,
                )
            ),
            signal_key=evaluation.signal_key,
            pre_point_count=evaluation.pre_point_count,
            post_point_count=evaluation.post_point_count,
            eligible=evaluation.eligible,
            absolute_scale_floor=evaluation.absolute_scale_floor,
            relative_scale_floor=frozen_policy.relative_scale_floor,
            candidate=evaluation.candidate,
        )
        for evaluation in evaluations
    )
    ledger = MetricEvidenceLedger(
        schema_version=SCHEMA_VERSION,
        tenant_id=tenant,
        incident_id=incident,
        run_id=run,
        window=normalized_window,
        policy=frozen_policy,
        decision=decision,
        entries=entries,
    )
    return validate_metric_evidence_ledger(ledger)


def compile_metric_shift_ledger(
    tenant_id: TenantId,
    incident_id: IncidentId,
    run_id: RunId,
    window: IncidentWindow,
    baseline_result: BaselineResult,
) -> MetricEvidenceLedger:
    """Compile trusted Phase 1 types and normalize every malformed object failure."""
    if type(baseline_result) not in {BaselineRanking, BaselineAbstention}:
        raise InvalidEvidenceLedgerError
    try:
        return _compile_metric_shift_ledger(
            tenant_id,
            incident_id,
            run_id,
            window,
            baseline_result,
        )
    except InvalidEvidenceLedgerError:
        raise
    except Exception:
        raise InvalidEvidenceLedgerError from None
