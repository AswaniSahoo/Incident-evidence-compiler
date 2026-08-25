"""Behavior and failure-semantics tests for the persistence boundary.

Hermetic: everything here runs against the in-memory fakes with no database, network,
or credentials, so it belongs in the locked gate. The real ``SKIP LOCKED`` claim race
is covered separately by opt-in integration tests against PostgreSQL.
"""

import subprocess
import sys
import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from incident_evidence_compiler.domain.identifiers import (
    EvidenceId,
    IncidentId,
    RunId,
    TenantId,
)
from incident_evidence_compiler.domain.incidents import IncidentWindow
from incident_evidence_compiler.persistence import (
    AttemptId,
    AttemptRecord,
    AuditRecord,
    EvidenceRecord,
    IdempotencyConflictError,
    InMemoryUnitOfWorkFactory,
    InvalidPersistenceRecordError,
    InvestigationId,
    InvestigationRecord,
    InvestigationStatus,
    JobId,
    JobRecord,
    JobStatus,
    LedgerKind,
    RecordNotFoundError,
    ReportRecord,
)

_MOMENT = datetime(2026, 1, 1, tzinfo=UTC)
_LEASE = timedelta(minutes=5)


def _window() -> IncidentWindow:
    return IncidentWindow(
        start=_MOMENT,
        injection=_MOMENT + timedelta(minutes=2),
        end=_MOMENT + timedelta(minutes=10),
    )


def _investigation(
    *,
    tenant: str = "tenant-a",
    incident: str = "inc-1",
    run: str = "run-1",
    key: str | None = None,
    investigation_id: UUID | None = None,
    status: InvestigationStatus = InvestigationStatus.PENDING,
) -> InvestigationRecord:
    return InvestigationRecord(
        investigation_id=InvestigationId(investigation_id or uuid4()),
        tenant=TenantId(tenant),
        incident=IncidentId(incident),
        run=RunId(run),
        window=_window(),
        status=status,
        idempotency_key=key,
        created_at=_MOMENT,
        updated_at=_MOMENT,
    )


def _job(
    *,
    investigation_id: InvestigationId,
    tenant: str = "tenant-a",
    job_id: UUID | None = None,
    status: JobStatus = JobStatus.QUEUED,
    available_at: datetime | None = None,
) -> JobRecord:
    return JobRecord(
        job_id=JobId(job_id or uuid4()),
        investigation_id=investigation_id,
        tenant=TenantId(tenant),
        status=status,
        available_at=available_at or _MOMENT,
        claimed_by=None,
        claimed_at=None,
        lease_expires_at=None,
        attempt_count=0,
        max_attempts=3,
        created_at=_MOMENT,
        updated_at=_MOMENT,
    )


def _evidence(
    *,
    investigation_id: InvestigationId,
    evidence_id: str,
    tenant: str = "tenant-a",
    run: str = "run-1",
    payload: str = '{"v":1}',
) -> EvidenceRecord:
    return EvidenceRecord(
        tenant=TenantId(tenant),
        investigation_id=investigation_id,
        run=RunId(run),
        evidence_id=EvidenceId(evidence_id),
        ledger_kind=LedgerKind.METRIC,
        schema_version="metric-evidence.v1",
        payload=payload,
        created_at=_MOMENT,
    )


class InvestigationRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_is_idempotent_by_key(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        first = _investigation(key="idem-1")
        async with factory() as uow:
            stored = await uow.investigations.create(first)
            await uow.commit()
        self.assertEqual(stored, first)

        replay = _investigation(key="idem-1")  # different surrogate id, same key
        async with factory() as uow:
            returned = await uow.investigations.create(replay)
            await uow.commit()
        self.assertEqual(returned.investigation_id, first.investigation_id)

        async with factory() as uow:
            with self.assertRaises(RecordNotFoundError):
                await uow.investigations.get(first.tenant, replay.investigation_id)

    async def test_duplicate_surrogate_id_conflicts(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation()
        async with factory() as uow:
            await uow.investigations.create(investigation)
            await uow.commit()
        async with factory() as uow:
            with self.assertRaises(IdempotencyConflictError):
                await uow.investigations.create(investigation)

    async def test_get_is_tenant_scoped(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation(tenant="tenant-a")
        async with factory() as uow:
            await uow.investigations.create(investigation)
            await uow.commit()
        async with factory() as uow:
            with self.assertRaises(RecordNotFoundError):
                await uow.investigations.get(TenantId("tenant-b"), investigation.investigation_id)

    async def test_set_status_updates(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation()
        async with factory() as uow:
            await uow.investigations.create(investigation)
            updated = await uow.investigations.set_status(
                investigation.tenant, investigation.investigation_id, InvestigationStatus.RUNNING
            )
            await uow.commit()
        self.assertEqual(updated.status, InvestigationStatus.RUNNING)

    async def test_get_returns_committed_record(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation()
        async with factory() as uow:
            await uow.investigations.create(investigation)
            await uow.commit()
        async with factory() as uow:
            got = await uow.investigations.get(investigation.tenant, investigation.investigation_id)
        self.assertEqual(got, investigation)


class TransactionTest(unittest.IsolatedAsyncioTestCase):
    async def test_uncommitted_work_is_discarded(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation()
        async with factory() as uow:
            await uow.investigations.create(investigation)
            # leave scope without committing
        async with factory() as uow:
            with self.assertRaises(RecordNotFoundError):
                await uow.investigations.get(investigation.tenant, investigation.investigation_id)

    async def test_rollback_discards_work(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation()
        async with factory() as uow:
            await uow.investigations.create(investigation)
            await uow.rollback()
            await uow.commit()
        async with factory() as uow:
            with self.assertRaises(RecordNotFoundError):
                await uow.investigations.get(investigation.tenant, investigation.investigation_id)

    async def test_exception_releases_lock_and_discards_work(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation()

        class _Boom(Exception):
            pass

        with self.assertRaises(_Boom):
            async with factory() as uow:
                await uow.investigations.create(investigation)
                raise _Boom

        # A new scope must be able to acquire the lock (it was released on the
        # exception path), and the uncommitted write must not be visible.
        async with factory() as uow:
            with self.assertRaises(RecordNotFoundError):
                await uow.investigations.get(investigation.tenant, investigation.investigation_id)


class JobQueueTest(unittest.IsolatedAsyncioTestCase):
    async def test_claim_returns_each_job_once(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation()
        job_a = _job(investigation_id=investigation.investigation_id)
        job_b = _job(investigation_id=investigation.investigation_id)
        async with factory() as uow:
            await uow.jobs.enqueue(job_a)
            await uow.jobs.enqueue(job_b)
            await uow.commit()

        now = _MOMENT + timedelta(seconds=1)
        async with factory() as uow:
            first = await uow.jobs.claim("worker-1", lease=_LEASE, now=now)
            second = await uow.jobs.claim("worker-2", lease=_LEASE, now=now)
            third = await uow.jobs.claim("worker-3", lease=_LEASE, now=now)
            await uow.commit()

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNone(third)
        assert first is not None and second is not None
        self.assertEqual(
            {first.job_id.value, second.job_id.value},
            {job_a.job_id.value, job_b.job_id.value},
        )

    async def test_claim_is_fifo_by_available_at(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation()
        later = _job(
            investigation_id=investigation.investigation_id,
            available_at=_MOMENT + timedelta(minutes=1),
        )
        earlier = _job(investigation_id=investigation.investigation_id, available_at=_MOMENT)
        async with factory() as uow:
            await uow.jobs.enqueue(later)
            await uow.jobs.enqueue(earlier)
            await uow.commit()
        async with factory() as uow:
            claimed = await uow.jobs.claim(
                "worker-1", lease=_LEASE, now=_MOMENT + timedelta(minutes=2)
            )
            await uow.commit()
        assert claimed is not None
        self.assertEqual(claimed.job_id.value, earlier.job_id.value)

    async def test_claim_respects_available_at(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation()
        future = _job(
            investigation_id=investigation.investigation_id,
            available_at=_MOMENT + timedelta(hours=1),
        )
        async with factory() as uow:
            await uow.jobs.enqueue(future)
            await uow.commit()
        async with factory() as uow:
            claimed = await uow.jobs.claim("worker-1", lease=_LEASE, now=_MOMENT)
            await uow.commit()
        self.assertIsNone(claimed)

    async def test_expired_lease_is_reclaimable(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation()
        job = _job(investigation_id=investigation.investigation_id)
        async with factory() as uow:
            await uow.jobs.enqueue(job)
            await uow.commit()

        async with factory() as uow:
            first = await uow.jobs.claim("worker-1", lease=_LEASE, now=_MOMENT)
            blocked = await uow.jobs.claim(
                "worker-2", lease=_LEASE, now=_MOMENT + timedelta(minutes=1)
            )
            await uow.commit()
        assert first is not None
        self.assertIsNone(blocked)

        async with factory() as uow:
            reclaimed = await uow.jobs.claim(
                "worker-2", lease=_LEASE, now=_MOMENT + timedelta(minutes=6)
            )
            await uow.commit()
        assert reclaimed is not None
        self.assertEqual(reclaimed.job_id.value, job.job_id.value)
        self.assertEqual(reclaimed.attempt_count, 2)

    async def test_claim_requires_worker_id(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        async with factory() as uow:
            with self.assertRaises(InvalidPersistenceRecordError):
                await uow.jobs.claim("   ", lease=_LEASE, now=_MOMENT)

    async def test_get_is_tenant_scoped(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation()
        job = _job(investigation_id=investigation.investigation_id)
        async with factory() as uow:
            await uow.jobs.enqueue(job)
            await uow.commit()
        async with factory() as uow:
            with self.assertRaises(RecordNotFoundError):
                await uow.jobs.get(TenantId("tenant-b"), job.job_id)


class AttemptRepositoryTest(unittest.IsolatedAsyncioTestCase):
    def _attempt(self, job_id: JobId, number: int) -> AttemptRecord:
        return AttemptRecord(
            attempt_id=AttemptId(uuid4()),
            job_id=job_id,
            tenant=TenantId("tenant-a"),
            attempt_number=number,
            worker_id="worker-1",
            started_at=_MOMENT,
            finished_at=None,
            outcome=None,
            error_code=None,
            created_at=_MOMENT,
        )

    async def test_attempt_number_is_unique_per_job(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        job_id = JobId(uuid4())
        async with factory() as uow:
            await uow.attempts.record(self._attempt(job_id, 1))
            with self.assertRaises(IdempotencyConflictError):
                await uow.attempts.record(self._attempt(job_id, 1))
            await uow.attempts.record(self._attempt(job_id, 2))
            await uow.commit()
        async with factory() as uow:
            attempts = await uow.attempts.list_for_job(TenantId("tenant-a"), job_id)
        self.assertEqual([a.attempt_number for a in attempts], [1, 2])


class EvidenceRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_append_is_idempotent_by_content_id(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation()
        evidence = _evidence(investigation_id=investigation.investigation_id, evidence_id="ev-1")
        async with factory() as uow:
            await uow.evidence.append([evidence])
            await uow.evidence.append([evidence])
            await uow.commit()
        async with factory() as uow:
            stored = await uow.evidence.list_for_investigation(
                investigation.tenant, investigation.investigation_id
            )
        self.assertEqual(len(stored), 1)

    async def test_list_is_tenant_scoped(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation(tenant="tenant-a")
        evidence = _evidence(investigation_id=investigation.investigation_id, evidence_id="ev-1")
        async with factory() as uow:
            await uow.evidence.append([evidence])
            await uow.commit()
        async with factory() as uow:
            other = await uow.evidence.list_for_investigation(
                TenantId("tenant-b"), investigation.investigation_id
            )
        self.assertEqual(other, ())

    async def test_append_keeps_first_content_for_same_id(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation()
        first = _evidence(
            investigation_id=investigation.investigation_id,
            evidence_id="ev-1",
            payload='{"v":1}',
        )
        second = _evidence(
            investigation_id=investigation.investigation_id,
            evidence_id="ev-1",
            payload='{"v":2}',
        )
        async with factory() as uow:
            await uow.evidence.append([first])
            (returned,) = await uow.evidence.append([second])
            await uow.commit()
        self.assertEqual(returned.payload, first.payload)
        async with factory() as uow:
            stored = await uow.evidence.list_for_investigation(
                investigation.tenant, investigation.investigation_id
            )
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].payload, first.payload)


class ReportRepositoryTest(unittest.IsolatedAsyncioTestCase):
    def _report(self, investigation: InvestigationRecord) -> ReportRecord:
        return ReportRecord(
            investigation_id=investigation.investigation_id,
            tenant=investigation.tenant,
            run=investigation.run,
            schema_version="verification.v1",
            payload='{"verdict":"UNKNOWN"}',
            created_at=_MOMENT,
        )

    async def test_put_once_then_conflict(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation()
        report = self._report(investigation)
        async with factory() as uow:
            await uow.reports.put(report)
            await uow.commit()
        async with factory() as uow:
            with self.assertRaises(IdempotencyConflictError):
                await uow.reports.put(report)

    async def test_get_is_tenant_scoped(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation(tenant="tenant-a")
        report = self._report(investigation)
        async with factory() as uow:
            await uow.reports.put(report)
            await uow.commit()
        async with factory() as uow:
            with self.assertRaises(RecordNotFoundError):
                await uow.reports.get(TenantId("tenant-b"), investigation.investigation_id)

    async def test_round_trip_preserves_baseline_payload(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation()
        report = ReportRecord(
            investigation_id=investigation.investigation_id,
            tenant=investigation.tenant,
            run=investigation.run,
            schema_version="verification.v1",
            payload='{"verdict":"UNKNOWN"}',
            created_at=_MOMENT,
            baseline_payload='{"kind":"ranking"}',
        )
        async with factory() as uow:
            await uow.reports.put(report)
            await uow.commit()
        async with factory() as uow:
            stored = await uow.reports.get(report.tenant, investigation.investigation_id)
        self.assertEqual(stored.baseline_payload, '{"kind":"ranking"}')
        self.assertIsNone(self._report(investigation).baseline_payload)


class AuditLogTest(unittest.IsolatedAsyncioTestCase):
    async def test_append_and_list_for_investigation(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation = _investigation()
        entry = AuditRecord(
            tenant=investigation.tenant,
            investigation_id=investigation.investigation_id,
            actor="worker-1",
            action="job.claimed",
            detail=None,
            occurred_at=_MOMENT,
        )
        async with factory() as uow:
            await uow.audit.record(entry)
            await uow.commit()
        async with factory() as uow:
            entries = await uow.audit.list_for_investigation(
                investigation.tenant, investigation.investigation_id
            )
        self.assertEqual(entries, (entry,))


class DependencyDirectionTest(unittest.TestCase):
    def test_domain_import_does_not_load_persistence(self) -> None:
        code = (
            "import sys; import incident_evidence_compiler.domain; "
            "assert 'incident_evidence_compiler.persistence' not in sys.modules"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
