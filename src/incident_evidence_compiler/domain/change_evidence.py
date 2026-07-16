"""Immutable, content-bound change-event evidence ledgers.

This ledger binds a validated change-event log to an exact tenant/incident/run
context and classifies each event's timing relative to the incident window. It
mirrors the metric-evidence ledger's discipline: deep reconstruction,
content-bound evidence IDs, canonical ordering, and no silent repair. It is kept
separate from the metric ledger so no existing content ID or serialization
changes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, NoReturn

from .changes import MAX_CHANGE_EVENTS, ChangeEvent, ChangeEventKey, ChangeEventLog, ChangeKind
from .errors import InvalidChangeEventLedgerError
from .identifiers import EvidenceId, IncidentId, RunId, TenantId
from .incidents import IncidentWindow

SCHEMA_VERSION = "change-event-ledger.v1"
_ID_DOMAIN = b"incident-evidence-compiler.change-event-evidence.v1\x00"


class ChangePhase(StrEnum):
    """A change event's timing relative to the incident window."""

    BEFORE_WINDOW = "before_window"
    PRE_INJECTION = "pre_injection"
    POST_INJECTION = "post_injection"
    AFTER_WINDOW = "after_window"


@dataclass(frozen=True, slots=True, repr=False)
class ChangeEventEvidence:
    """Replayable evidence for exactly one observed change event."""

    evidence_id: EvidenceId
    event_key: ChangeEventKey
    kind: ChangeKind
    occurred_at: datetime
    phase: ChangePhase

    def __repr__(self) -> str:
        return f"ChangeEventEvidence(phase='{self.phase.value}')"


@dataclass(frozen=True, slots=True, repr=False)
class ChangeEventLedger:
    """One immutable change-event log bound to an exact incident run context."""

    schema_version: str
    tenant_id: TenantId
    incident_id: IncidentId
    run_id: RunId
    window: IncidentWindow
    entries: tuple[ChangeEventEvidence, ...]

    def __repr__(self) -> str:
        return (
            f"ChangeEventLedger(schema_version='{self.schema_version}', "
            f"entry_count={len(self.entries)})"
        )


def _invalid() -> NoReturn:
    raise InvalidChangeEventLedgerError


def _identifier[IdentifierT: (TenantId, IncidentId, RunId)](
    identifier: object, expected_type: type[IdentifierT]
) -> IdentifierT:
    if type(identifier) is not expected_type:
        _invalid()
    try:
        value = identifier.value
    except Exception:
        _invalid()
    if not isinstance(value, str) or not value.strip():
        _invalid()
    try:
        return expected_type(value)
    except Exception:
        _invalid()


def _window(value: object) -> IncidentWindow:
    if type(value) is not IncidentWindow:
        _invalid()
    try:
        timestamps = (value.start, value.injection, value.end)
        if not all(isinstance(item, datetime) and item.tzinfo is not None for item in timestamps):
            _invalid()
        if any(item.utcoffset() is None for item in timestamps):
            _invalid()
        normalized = tuple(item.astimezone(UTC) for item in timestamps)
        if not normalized[0] <= normalized[1] < normalized[2]:
            _invalid()
        return IncidentWindow(*normalized)
    except InvalidChangeEventLedgerError:
        raise
    except Exception:
        raise InvalidChangeEventLedgerError from None


def _event_key(value: object) -> ChangeEventKey:
    if type(value) is not ChangeEventKey:
        _invalid()
    try:
        raw = value.value
    except Exception:
        _invalid()
    if not isinstance(raw, str) or not raw.strip():
        _invalid()
    try:
        return ChangeEventKey(raw)
    except Exception:
        _invalid()


def _kind(value: object) -> ChangeKind:
    if type(value) is not ChangeKind:
        _invalid()
    try:
        return ChangeKind(value.value)
    except Exception:
        _invalid()


def _occurred_at(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        _invalid()
    try:
        if value.utcoffset() is None:
            _invalid()
        return value.astimezone(UTC)
    except InvalidChangeEventLedgerError:
        raise
    except Exception:
        raise InvalidChangeEventLedgerError from None


def _phase(occurred_at: datetime, window: IncidentWindow) -> ChangePhase:
    if occurred_at < window.start:
        return ChangePhase.BEFORE_WINDOW
    if occurred_at < window.injection:
        return ChangePhase.PRE_INJECTION
    if occurred_at < window.end:
        return ChangePhase.POST_INJECTION
    return ChangePhase.AFTER_WINDOW


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _entry_payload(
    tenant_id: TenantId,
    incident_id: IncidentId,
    run_id: RunId,
    window: IncidentWindow,
    event_key: ChangeEventKey,
    kind: ChangeKind,
    occurred_at: datetime,
    phase: ChangePhase,
) -> dict[str, Any]:
    return {
        "event_key": event_key.value,
        "incident_id": incident_id.value,
        "incident_window": {
            "end": _timestamp(window.end),
            "injection": _timestamp(window.injection),
            "start": _timestamp(window.start),
        },
        "kind": kind.value,
        "occurred_at": _timestamp(occurred_at),
        "phase": phase.value,
        "run_id": run_id.value,
        "schema_version": SCHEMA_VERSION,
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
        raise InvalidChangeEventLedgerError from None


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


def _order_key(event: ChangeEvent) -> tuple[datetime, str, str]:
    return (event.occurred_at, event.kind.value, event.event_key.value)


def _build_entries(
    tenant: TenantId,
    incident: IncidentId,
    run: RunId,
    window: IncidentWindow,
    events: tuple[ChangeEvent, ...],
) -> tuple[ChangeEventEvidence, ...]:
    ordered = sorted(events, key=_order_key)
    entries: list[ChangeEventEvidence] = []
    for event in ordered:
        event_key = _event_key(event.event_key)
        kind = _kind(event.kind)
        occurred_at = _occurred_at(event.occurred_at)
        phase = _phase(occurred_at, window)
        entries.append(
            ChangeEventEvidence(
                evidence_id=_evidence_id(
                    _entry_payload(
                        tenant, incident, run, window, event_key, kind, occurred_at, phase
                    )
                ),
                event_key=event_key,
                kind=kind,
                occurred_at=occurred_at,
                phase=phase,
            )
        )
    return tuple(entries)


def _change_log(value: object) -> tuple[ChangeEvent, ...]:
    if type(value) is not ChangeEventLog:
        _invalid()
    events = value.events
    if not isinstance(events, tuple) or len(events) > MAX_CHANGE_EVENTS:
        _invalid()
    reconstructed: list[ChangeEvent] = []
    seen: set[tuple[str, str, datetime]] = set()
    for event in events:
        if type(event) is not ChangeEvent:
            _invalid()
        event_key = _event_key(event.event_key)
        kind = _kind(event.kind)
        occurred_at = _occurred_at(event.occurred_at)
        identity = (event_key.value, kind.value, occurred_at)
        if identity in seen:
            _invalid()
        seen.add(identity)
        reconstructed.append(ChangeEvent(event_key, kind, occurred_at))
    return tuple(reconstructed)


def _validated_change_event_ledger(value: object) -> ChangeEventLedger:
    if type(value) is not ChangeEventLedger or value.schema_version != SCHEMA_VERSION:
        _invalid()
    tenant = _identifier(value.tenant_id, TenantId)
    incident = _identifier(value.incident_id, IncidentId)
    run = _identifier(value.run_id, RunId)
    normalized_window = _window(value.window)
    if not isinstance(value.entries, tuple):
        _invalid()

    supplied_ids: list[str] = []
    reconstructed: list[ChangeEvent] = []
    seen: set[tuple[str, str, datetime]] = set()
    for entry in value.entries:
        if type(entry) is not ChangeEventEvidence:
            _invalid()
        evidence_id = _evidence_identifier(entry.evidence_id)
        event_key = _event_key(entry.event_key)
        kind = _kind(entry.kind)
        occurred_at = _occurred_at(entry.occurred_at)
        if type(entry.phase) is not ChangePhase:
            _invalid()
        if entry.phase is not _phase(occurred_at, normalized_window):
            _invalid()
        identity = (event_key.value, kind.value, occurred_at)
        if identity in seen:
            _invalid()
        seen.add(identity)
        reconstructed.append(ChangeEvent(event_key, kind, occurred_at))
        supplied_ids.append(evidence_id.value)

    if [_order_key(event) for event in reconstructed] != [
        _order_key(event) for event in sorted(reconstructed, key=_order_key)
    ]:
        _invalid()
    entries = _build_entries(tenant, incident, run, normalized_window, tuple(reconstructed))
    if [entry.evidence_id.value for entry in entries] != supplied_ids:
        _invalid()
    return ChangeEventLedger(
        schema_version=SCHEMA_VERSION,
        tenant_id=tenant,
        incident_id=incident,
        run_id=run,
        window=normalized_window,
        entries=entries,
    )


def validate_change_event_ledger(value: object) -> ChangeEventLedger:
    """Deeply reconstruct a change ledger and verify every content-bound ID."""
    try:
        return _validated_change_event_ledger(value)
    except InvalidChangeEventLedgerError:
        raise
    except Exception:
        raise InvalidChangeEventLedgerError from None


def _compile_change_event_ledger(
    tenant_id: TenantId,
    incident_id: IncidentId,
    run_id: RunId,
    window: IncidentWindow,
    change_log: ChangeEventLog,
) -> ChangeEventLedger:
    tenant = _identifier(tenant_id, TenantId)
    incident = _identifier(incident_id, IncidentId)
    run = _identifier(run_id, RunId)
    normalized_window = _window(window)
    events = _change_log(change_log)
    entries = _build_entries(tenant, incident, run, normalized_window, events)
    ledger = ChangeEventLedger(
        schema_version=SCHEMA_VERSION,
        tenant_id=tenant,
        incident_id=incident,
        run_id=run,
        window=normalized_window,
        entries=entries,
    )
    return validate_change_event_ledger(ledger)


def compile_change_event_ledger(
    tenant_id: TenantId,
    incident_id: IncidentId,
    run_id: RunId,
    window: IncidentWindow,
    change_log: ChangeEventLog,
) -> ChangeEventLedger:
    """Validate and bind a change-event log without repairing forged state."""
    if type(change_log) is not ChangeEventLog:
        raise InvalidChangeEventLedgerError
    try:
        return _compile_change_event_ledger(tenant_id, incident_id, run_id, window, change_log)
    except InvalidChangeEventLedgerError:
        raise
    except Exception:
        raise InvalidChangeEventLedgerError from None
