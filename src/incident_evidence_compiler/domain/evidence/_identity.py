"""Canonical payloads and content-bound evidence identifiers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from ..baseline import BaselinePolicy, SignalEvaluation, SuspicionCandidate
from ..errors import InvalidEvidenceLedgerError
from ..identifiers import EvidenceId, IncidentId, RunId, TenantId
from ..incidents import IncidentWindow
from ._parsing import _invalid
from .types import SCHEMA_VERSION, MetricShiftDecision

_ID_DOMAIN = b"incident-evidence-compiler.metric-shift-evidence.v1\x00"


def _hex(value: float | None) -> str | None:
    return None if value is None else value.hex()


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _policy_payload(policy: BaselinePolicy) -> dict[str, object]:
    return {
        "minimum_margin": policy.minimum_margin.hex(),
        "minimum_points_per_window": policy.minimum_points_per_window,
        "minimum_score": policy.minimum_score.hex(),
        "relative_scale_floor": policy.relative_scale_floor.hex(),
    }


def _decision_payload(decision: MetricShiftDecision) -> dict[str, object]:
    return {
        "abstention_reason": (
            None if decision.abstention_reason is None else decision.abstention_reason.value
        ),
        "candidate_signal_keys": [key.value for key in decision.candidate_signal_keys],
        "eligible_signal_count": decision.eligible_signal_count,
        "kind": decision.kind.value,
        "lead": _hex(decision.lead),
        "second_score": _hex(decision.second_score),
        "top_score": _hex(decision.top_score),
    }


def _candidate_payload(candidate: SuspicionCandidate | None) -> dict[str, object] | None:
    if candidate is None:
        return None
    return {
        "absolute_scale_floor": candidate.absolute_scale_floor.hex(),
        "post_median": candidate.post_median.hex(),
        "post_point_count": candidate.post_point_count,
        "pre_mad": candidate.pre_mad.hex(),
        "pre_median": candidate.pre_median.hex(),
        "pre_point_count": candidate.pre_point_count,
        "relative_scale_floor": candidate.relative_scale_floor.hex(),
        "scale": candidate.scale.hex(),
        "signal_key": candidate.signal_key.value,
        "signed_score": candidate.signed_score.hex(),
        "suspicion_score": candidate.suspicion_score.hex(),
    }


def _entry_payload(
    tenant_id: TenantId,
    incident_id: IncidentId,
    run_id: RunId,
    window: IncidentWindow,
    policy: BaselinePolicy,
    decision: MetricShiftDecision,
    evaluation: SignalEvaluation,
) -> dict[str, Any]:
    return {
        "absolute_scale_floor": evaluation.absolute_scale_floor.hex(),
        "candidate": _candidate_payload(evaluation.candidate),
        "decision": _decision_payload(decision),
        "eligible": evaluation.eligible,
        "incident_id": incident_id.value,
        "incident_window": {
            "end": _timestamp(window.end),
            "injection": _timestamp(window.injection),
            "start": _timestamp(window.start),
        },
        "policy": _policy_payload(policy),
        "post_point_count": evaluation.post_point_count,
        "pre_point_count": evaluation.pre_point_count,
        "relative_scale_floor": policy.relative_scale_floor.hex(),
        "run_id": run_id.value,
        "schema_version": SCHEMA_VERSION,
        "signal_key": evaluation.signal_key.value,
        "tenant_id": tenant_id.value,
    }


def _evidence_id(payload: dict[str, Any]) -> EvidenceId:
    try:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(_ID_DOMAIN + canonical).hexdigest()
        return EvidenceId(f"sha256:{digest}")
    except Exception:
        raise InvalidEvidenceLedgerError from None


def _evidence_identifier(value: object) -> EvidenceId:
    if type(value) is not EvidenceId:
        _invalid()
    raw = value.value
    prefix, separator, digest = raw.partition(":") if isinstance(raw, str) else ("", "", "")
    if (
        separator != ":"
        or prefix != "sha256"
        or len(digest) != 64
        or digest != digest.lower()
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        _invalid()
    return EvidenceId(raw)
