"""Opt-in PostgreSQL integration tests for the psycopg driver and migration runner.

These require a real PostgreSQL reachable via the ``DATABASE_URL`` environment variable
(see docker-compose.yml) and are skipped otherwise, so the locked CI gate stays hermetic
and needs no database, network, or credentials. The two-worker SKIP LOCKED race test is
added in the next slice.

Run locally:
    docker compose up -d
    $env:DATABASE_URL = "postgresql://iec:iec@localhost:5432/iec"
    uv run --locked python -m unittest tests.test_persistence_postgres -v
"""

import asyncio
import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg

from incident_evidence_compiler.domain.identifiers import (
    EvidenceId,
    IncidentId,
    RunId,
    TenantId,
)
from incident_evidence_compiler.domain.incidents import IncidentWindow
from incident_evidence_compiler.persistence import (
    EvidenceRecord,
    IdempotencyConflictError,
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
from incident_evidence_compiler.persistence.migrations import apply_migrations
from incident_evidence_compiler.persistence.postgres import PostgresUnitOfWorkFactory

_DATABASE_URL = os.environ.get("DATABASE_URL")

# psycopg's async connection cannot run on Windows' default ProactorEventLoop. Only when
# the integration tests are enabled (DATABASE_URL set) do we select the selector-based
# policy, so the hermetic gate, which skips these tests, is left untouched.
if _DATABASE_URL is not None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
_MOMENT = datetime(2026, 1, 1, tzinfo=UTC)
_LEASE = timedelta(minutes=5)
_TABLES = "audit, reports, evidence, attempts, jobs, investigations"


def _window() -> IncidentWindow:
    return IncidentWindow(
        start=_MOMENT,
        injection=_MOMENT + timedelta(minutes=2),
        end=_MOMENT + timedelta(minutes=10),
    )


def _investigation(
    *, tenant: str = "tenant-a", key: str | None = None, investigation_id: UUID | None = None
) -> InvestigationRecord:
    return InvestigationRecord(
        investigation_id=InvestigationId(investigation_id or uuid4()),
        tenant=TenantId(tenant),
        incident=IncidentId("inc-1"),
        run=RunId("run-1"),
        window=_window(),
        status=InvestigationStatus.PENDING,
        idempotency_key=key,
        created_at=_MOMENT,
        updated_at=_MOMENT,
    )


def _job(*, investigation_id: InvestigationId, tenant: str = "tenant-a") -> JobRecord:
    return JobRecord(
        job_id=JobId(uuid4()),
        investigation_id=investigation_id,
        tenant=TenantId(tenant),
        status=JobStatus.QUEUED,
        available_at=_MOMENT,
        claimed_by=None,
        claimed_at=None,
        lease_expires_at=None,
        attempt_count=0,
        max_attempts=3,
        created_at=_MOMENT,
        updated_at=_MOMENT,
    )


def _evidence(*, investigation_id: InvestigationId, evidence_id: str) -> EvidenceRecord:
    return EvidenceRecord(
        tenant=TenantId("tenant-a"),
        investigation_id=investigation_id,
        run=RunId("run-1"),
        evidence_id=EvidenceId(evidence_id),
        ledger_kind=LedgerKind.METRIC,
        schema_version="metric-evidence.v1",
        payload='{"v":1}',
        created_at=_MOMENT,
    )


@unittest.skipUnless(_DATABASE_URL, "requires DATABASE_URL for PostgreSQL integration")
class PostgresPersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        assert _DATABASE_URL is not None
        self._dsn = _DATABASE_URL
        self._conn = await psycopg.AsyncConnection.connect(self._dsn, autocommit=False)
        await apply_migrations(self._conn)
        async with self._conn.cursor() as cursor:
            await cursor.execute(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE")
        await self._conn.commit()
        self.factory = PostgresUnitOfWorkFactory(self._dsn)

    async def asyncTearDown(self) -> None:
        await self._conn.close()

    async def test_migrations_are_idempotent(self) -> None:
        second = await apply_migrations(self._conn)
        self.assertEqual(second, ())

    async def test_investigation_create_is_idempotent_by_key(self) -> None:
        first = _investigation(key="idem-1")
        async with self.factory() as uow:
            await uow.investigations.create(first)
            await uow.commit()
        async with self.factory() as uow:
            returned = await uow.investigations.create(_investigation(key="idem-1"))
            await uow.commit()
        self.assertEqual(returned.investigation_id, first.investigation_id)

    async def test_get_is_tenant_scoped(self) -> None:
        investigation = _investigation(tenant="tenant-a")
        async with self.factory() as uow:
            await uow.investigations.create(investigation)
            await uow.commit()
        async with self.factory() as uow:
            with self.assertRaises(RecordNotFoundError):
                await uow.investigations.get(TenantId("tenant-b"), investigation.investigation_id)

    async def test_claim_returns_each_job_once(self) -> None:
        investigation = _investigation()
        job_a = _job(investigation_id=investigation.investigation_id)
        job_b = _job(investigation_id=investigation.investigation_id)
        async with self.factory() as uow:
            await uow.investigations.create(investigation)
            await uow.jobs.enqueue(job_a)
            await uow.jobs.enqueue(job_b)
            await uow.commit()
        now = _MOMENT + timedelta(seconds=1)
        async with self.factory() as uow:
            first = await uow.jobs.claim("worker-1", lease=_LEASE, now=now)
            second = await uow.jobs.claim("worker-1", lease=_LEASE, now=now)
            third = await uow.jobs.claim("worker-1", lease=_LEASE, now=now)
            await uow.commit()
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNone(third)
        assert first is not None and second is not None
        self.assertEqual(
            {first.job_id.value, second.job_id.value},
            {job_a.job_id.value, job_b.job_id.value},
        )

    async def test_expired_lease_is_reclaimable(self) -> None:
        investigation = _investigation()
        job = _job(investigation_id=investigation.investigation_id)
        async with self.factory() as uow:
            await uow.investigations.create(investigation)
            await uow.jobs.enqueue(job)
            await uow.commit()
        async with self.factory() as uow:
            await uow.jobs.claim("worker-1", lease=_LEASE, now=_MOMENT)
            await uow.commit()
        async with self.factory() as uow:
            reclaimed = await uow.jobs.claim(
                "worker-2", lease=_LEASE, now=_MOMENT + timedelta(minutes=6)
            )
            await uow.commit()
        assert reclaimed is not None
        self.assertEqual(reclaimed.job_id.value, job.job_id.value)
        self.assertEqual(reclaimed.attempt_count, 2)

    async def test_evidence_append_is_idempotent(self) -> None:
        investigation = _investigation()
        evidence = _evidence(investigation_id=investigation.investigation_id, evidence_id="ev-1")
        async with self.factory() as uow:
            await uow.investigations.create(investigation)
            await uow.evidence.append([evidence])
            await uow.evidence.append([evidence])
            await uow.commit()
        async with self.factory() as uow:
            stored = await uow.evidence.list_for_investigation(
                investigation.tenant, investigation.investigation_id
            )
        self.assertEqual(len(stored), 1)

    async def test_report_put_once_then_conflict(self) -> None:
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
        async with self.factory() as uow:
            await uow.investigations.create(investigation)
            await uow.reports.put(report)
            await uow.commit()
        async with self.factory() as uow:
            stored = await uow.reports.get(report.tenant, investigation.investigation_id)
            self.assertEqual(stored.baseline_payload, '{"kind":"ranking"}')
            with self.assertRaises(IdempotencyConflictError):
                await uow.reports.put(report)

    async def test_two_workers_claim_each_job_exactly_once(self) -> None:
        investigation = _investigation()
        job_count = 25
        jobs = [_job(investigation_id=investigation.investigation_id) for _ in range(job_count)]
        async with self.factory() as uow:
            await uow.investigations.create(investigation)
            for job in jobs:
                await uow.jobs.enqueue(job)
            await uow.commit()

        now = _MOMENT + timedelta(seconds=1)

        async def worker(worker_id: str) -> list[UUID]:
            claimed: list[UUID] = []
            while True:
                # Each claim is its own transaction on its own connection; concurrent
                # workers exercise SELECT ... FOR UPDATE SKIP LOCKED.
                async with self.factory() as uow:
                    job = await uow.jobs.claim(worker_id, lease=_LEASE, now=now)
                    await uow.commit()
                if job is None:
                    return claimed
                claimed.append(job.job_id.value)

        first, second = await asyncio.gather(worker("worker-1"), worker("worker-2"))
        all_claimed = first + second
        expected = {job.job_id.value for job in jobs}
        self.assertEqual(len(all_claimed), job_count, "every job claimed exactly once")
        self.assertEqual(set(all_claimed), expected, "no job missed or double-claimed")


if __name__ == "__main__":
    unittest.main()
