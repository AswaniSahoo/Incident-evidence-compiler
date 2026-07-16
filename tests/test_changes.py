from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

from incident_evidence_compiler.domain.change_evidence import (
    SCHEMA_VERSION,
    ChangeEventLedger,
    ChangePhase,
    compile_change_event_ledger,
    validate_change_event_ledger,
)
from incident_evidence_compiler.domain.changes import (
    MAX_CHANGE_EVENTS,
    ChangeEvent,
    ChangeEventKey,
    ChangeEventLog,
    ChangeKind,
)
from incident_evidence_compiler.domain.errors import (
    InvalidChangeEventError,
    InvalidChangeEventLedgerError,
    InvalidTimestampError,
)
from incident_evidence_compiler.domain.identifiers import EvidenceId, IncidentId, RunId, TenantId
from incident_evidence_compiler.domain.incidents import IncidentWindow

BASE = datetime(2026, 1, 1, tzinfo=UTC)
TENANT = TenantId("tenant-01")
INCIDENT = IncidentId("incident-01")
RUN = RunId("run-01")
# A fixed content-ID vector: tenant-01/incident-01/run-01, the window below, and
# one DEPLOYMENT of svc-checkout five minutes in (pre-injection).
KNOWN_EVIDENCE_ID = "sha256:35b33f12068c901877ca6c6b4b95840db75027d633f1bc4a6733e0a733f399ee"


def window() -> IncidentWindow:
    return IncidentWindow(BASE, BASE + timedelta(minutes=10), BASE + timedelta(minutes=20))


def event(name: str, kind: ChangeKind, minute: float) -> ChangeEvent:
    return ChangeEvent(ChangeEventKey(name), kind, BASE + timedelta(minutes=minute))


def ledger(*events: ChangeEvent) -> ChangeEventLedger:
    return compile_change_event_ledger(TENANT, INCIDENT, RUN, window(), ChangeEventLog(events))


class ChangeEventContractTests(unittest.TestCase):
    def test_event_key_rejects_empty_and_non_string(self) -> None:
        for value in ("", "   ", 5, None):
            with self.subTest(value=value):
                with self.assertRaises(InvalidChangeEventError):
                    ChangeEventKey(value)  # type: ignore[arg-type]

    def test_event_normalizes_timezone_and_rejects_bad_fields(self) -> None:
        ist = timezone(timedelta(hours=5, minutes=30))
        aware = datetime(2026, 1, 1, 5, 30, tzinfo=ist)
        normalized = ChangeEvent(ChangeEventKey("svc"), ChangeKind.DEPLOYMENT, aware)
        self.assertIs(normalized.occurred_at.tzinfo, UTC)
        self.assertEqual(normalized.occurred_at, BASE)
        with self.assertRaises(InvalidTimestampError):
            ChangeEvent(ChangeEventKey("svc"), ChangeKind.DEPLOYMENT, datetime(2026, 1, 1))
        with self.assertRaises(InvalidChangeEventError):
            ChangeEvent("svc", ChangeKind.DEPLOYMENT, BASE)  # type: ignore[arg-type]
        with self.assertRaises(InvalidChangeEventError):
            ChangeEvent(ChangeEventKey("svc"), "deployment", BASE)  # type: ignore[arg-type]

    def test_log_orders_canonically_and_materializes_once(self) -> None:
        source = [
            event("svc-b", ChangeKind.ROLLBACK, 15),
            event("svc-a", ChangeKind.DEPLOYMENT, 15),
            event("svc-a", ChangeKind.DEPLOYMENT, 5),
        ]
        log = ChangeEventLog(iter(source))
        source.append(event("svc-c", ChangeKind.SCALING, 1))
        self.assertEqual(len(log.events), 3)
        self.assertEqual(
            [(item.event_key.value, item.kind.value) for item in log.events],
            [("svc-a", "deployment"), ("svc-a", "deployment"), ("svc-b", "rollback")],
        )
        self.assertEqual(log.events[0].occurred_at, BASE + timedelta(minutes=5))

    def test_log_is_empty_valid_and_deeply_immutable(self) -> None:
        empty = ChangeEventLog(())
        self.assertEqual(empty.events, ())
        log = ChangeEventLog((event("svc", ChangeKind.DEPLOYMENT, 5),))
        with self.assertRaises(FrozenInstanceError):
            log.events = ()  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            log.events[0].kind = ChangeKind.ROLLBACK  # type: ignore[misc]

    def test_log_rejects_duplicates_excess_and_wrong_types(self) -> None:
        duplicate = event("svc", ChangeKind.DEPLOYMENT, 5)
        with self.assertRaises(InvalidChangeEventError):
            ChangeEventLog((duplicate, event("svc", ChangeKind.DEPLOYMENT, 5)))
        with self.assertRaises(InvalidChangeEventError):
            ChangeEventLog(("not-an-event",))  # type: ignore[arg-type]
        too_many = tuple(
            event(f"svc-{index}", ChangeKind.DEPLOYMENT, index)
            for index in range(MAX_CHANGE_EVENTS + 1)
        )
        with self.assertRaises(InvalidChangeEventError):
            ChangeEventLog(too_many)

    def test_log_permits_same_instant_for_distinct_key_or_kind(self) -> None:
        log = ChangeEventLog(
            (
                event("svc-a", ChangeKind.DEPLOYMENT, 5),
                event("svc-a", ChangeKind.ROLLBACK, 5),
                event("svc-b", ChangeKind.DEPLOYMENT, 5),
            )
        )
        self.assertEqual(len(log.events), 3)


class ChangeLedgerTests(unittest.TestCase):
    def test_one_entry_per_event_with_correct_phase_and_order(self) -> None:
        result = ledger(
            event("svc-late", ChangeKind.SCALING, 25),
            event("svc-post", ChangeKind.ROLLBACK, 15),
            event("svc-pre", ChangeKind.DEPLOYMENT, 5),
            event("svc-early", ChangeKind.CONFIGURATION, -5),
        )
        self.assertEqual(
            [(entry.event_key.value, entry.phase.value) for entry in result.entries],
            [
                ("svc-early", "before_window"),
                ("svc-pre", "pre_injection"),
                ("svc-post", "post_injection"),
                ("svc-late", "after_window"),
            ],
        )

    def test_phase_boundaries_are_half_open(self) -> None:
        cases = {
            -1: ChangePhase.BEFORE_WINDOW,
            0: ChangePhase.PRE_INJECTION,
            5: ChangePhase.PRE_INJECTION,
            10: ChangePhase.POST_INJECTION,
            19: ChangePhase.POST_INJECTION,
            20: ChangePhase.AFTER_WINDOW,
        }
        for minute, expected in cases.items():
            with self.subTest(minute=minute):
                result = ledger(event("svc", ChangeKind.DEPLOYMENT, minute))
                self.assertEqual(result.entries[0].phase, expected)

    def test_fixed_content_id_vector_and_order_invariance(self) -> None:
        one = ledger(event("svc-checkout", ChangeKind.DEPLOYMENT, 5))
        self.assertEqual(one.entries[0].evidence_id.value, KNOWN_EVIDENCE_ID)
        forward = ledger(
            event("svc-a", ChangeKind.DEPLOYMENT, 5),
            event("svc-b", ChangeKind.ROLLBACK, 15),
        )
        reverse = ledger(
            event("svc-b", ChangeKind.ROLLBACK, 15),
            event("svc-a", ChangeKind.DEPLOYMENT, 5),
        )
        self.assertEqual(
            [entry.evidence_id.value for entry in forward.entries],
            [entry.evidence_id.value for entry in reverse.entries],
        )

    def test_content_id_changes_with_every_committed_field(self) -> None:
        baseline = ledger(event("svc-checkout", ChangeKind.DEPLOYMENT, 5)).entries[0].evidence_id
        variants = (
            compile_change_event_ledger(TenantId("other"), INCIDENT, RUN, window(), _one_event()),
            compile_change_event_ledger(TENANT, IncidentId("other"), RUN, window(), _one_event()),
            compile_change_event_ledger(TENANT, INCIDENT, RunId("other"), window(), _one_event()),
            compile_change_event_ledger(
                TENANT,
                INCIDENT,
                RUN,
                IncidentWindow(BASE, BASE + timedelta(minutes=8), BASE + timedelta(minutes=20)),
                _one_event(),
            ),
            ledger(event("svc-other", ChangeKind.DEPLOYMENT, 5)),
            ledger(event("svc-checkout", ChangeKind.ROLLBACK, 5)),
            ledger(event("svc-checkout", ChangeKind.DEPLOYMENT, 6)),
        )
        seen = {baseline.value}
        for variant in variants:
            with self.subTest(entry=variant.entries[0].phase.value):
                self.assertNotIn(variant.entries[0].evidence_id.value, seen)
                seen.add(variant.entries[0].evidence_id.value)

    def test_empty_ledger_is_valid(self) -> None:
        result = compile_change_event_ledger(TENANT, INCIDENT, RUN, window(), ChangeEventLog(()))
        self.assertEqual(result.entries, ())
        self.assertEqual(validate_change_event_ledger(result).entries, ())

    def test_compile_rejects_wrong_types(self) -> None:
        with self.assertRaises(InvalidChangeEventLedgerError):
            compile_change_event_ledger(TENANT, INCIDENT, RUN, window(), "not-a-log")  # type: ignore[arg-type]
        with self.assertRaises(InvalidChangeEventLedgerError):
            compile_change_event_ledger(
                "tenant",  # type: ignore[arg-type]
                INCIDENT,
                RUN,
                window(),
                _one_event(),
            )

    def test_validate_rejects_forged_ledgers(self) -> None:
        valid = ledger(
            event("svc-a", ChangeKind.DEPLOYMENT, 5),
            event("svc-b", ChangeKind.ROLLBACK, 15),
        )
        forged_id = replace(
            valid,
            entries=(
                replace(valid.entries[0], evidence_id=EvidenceId(f"sha256:{'0' * 64}")),
                valid.entries[1],
            ),
        )
        wrong_phase = replace(
            valid,
            entries=(replace(valid.entries[0], phase=ChangePhase.AFTER_WINDOW), valid.entries[1]),
        )
        reordered = replace(valid, entries=(valid.entries[1], valid.entries[0]))
        duplicated = replace(valid, entries=(valid.entries[0], valid.entries[0]))
        wrong_schema = replace(valid, schema_version="change-event-ledger.v2")
        for forged in (forged_id, wrong_phase, reordered, duplicated, wrong_schema):
            with self.subTest(case=forged.schema_version):
                with self.assertRaises(InvalidChangeEventLedgerError):
                    validate_change_event_ledger(forged)

    def test_validate_rejects_non_ledger_and_bad_entries(self) -> None:
        with self.assertRaises(InvalidChangeEventLedgerError):
            validate_change_event_ledger("not-a-ledger")
        broken = ChangeEventLedger(
            schema_version=SCHEMA_VERSION,
            tenant_id=TENANT,
            incident_id=INCIDENT,
            run_id=RUN,
            window=window(),
            entries=("not-evidence",),  # type: ignore[arg-type]
        )
        with self.assertRaises(InvalidChangeEventLedgerError):
            validate_change_event_ledger(broken)

    def test_repr_is_bounded_and_leakage_safe(self) -> None:
        result = ledger(event("SVC_SECRET", ChangeKind.DEPLOYMENT, 5))
        text = repr(result) + repr(result.entries[0])
        for canary in ("SVC_SECRET", TENANT.value, INCIDENT.value, RUN.value, "deployment"):
            self.assertNotIn(canary, text)
        self.assertIn("entry_count=1", text)
        self.assertIn("phase='pre_injection'", text)

    def test_domain_error_is_stable_and_silent(self) -> None:
        with self.assertRaises(InvalidChangeEventLedgerError) as caught:
            validate_change_event_ledger(object())
        self.assertEqual(str(caught.exception), "invalid_change_event_ledger")


def _one_event() -> ChangeEventLog:
    return ChangeEventLog((event("svc-checkout", ChangeKind.DEPLOYMENT, 5),))


if __name__ == "__main__":
    unittest.main()
