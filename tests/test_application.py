"""Hermetic tests for the application core (use-cases + worker).

Everything runs against the in-memory persistence fake, the deterministic FakeLLMClient,
and an in-memory telemetry source, no server, database, network, or credentials, so the
full create -> enqueue -> worker -> verified report pipeline is exercised in the gate.
"""

import asyncio
import json
import unittest
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from incident_evidence_compiler.application import (
    CreateInvestigation,
    CreateInvestigationCommand,
    GetInvestigationStatus,
    GetReport,
    InMemoryTelemetrySource,
    InvestigationNotFoundError,
    ReportNotReadyError,
    Worker,
)
from incident_evidence_compiler.domain.baseline import SignalBaselineInput
from incident_evidence_compiler.domain.identifiers import IncidentId, RunId, TenantId
from incident_evidence_compiler.domain.incidents import IncidentWindow
from incident_evidence_compiler.domain.metrics import MetricPoint, MetricSignal, SignalKey
from incident_evidence_compiler.llm import FakeLLMClient, HypothesisRequest, LLMProposal
from incident_evidence_compiler.persistence import (
    InMemoryUnitOfWorkFactory,
    InvestigationStatus,
)

_TENANT = "tenant-a"
_INCIDENT = "inc-1"
_RUN = "run-1"
_SIGNAL = "cpu"
_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _window() -> IncidentWindow:
    return IncidentWindow(
        start=_BASE,
        injection=_BASE + timedelta(minutes=10),
        end=_BASE + timedelta(minutes=20),
    )


def _signals() -> list[SignalBaselineInput]:
    pre = [MetricPoint(_BASE + timedelta(minutes=i), 1.0) for i in range(3)]
    post = [MetricPoint(_BASE + timedelta(minutes=10 + i), 10.0) for i in range(3)]
    signal = MetricSignal(SignalKey(_SIGNAL), tuple(pre + post))
    return [SignalBaselineInput(signal=signal, absolute_scale_floor=1.0)]


def _command(key: str | None = None) -> CreateInvestigationCommand:
    return CreateInvestigationCommand(
        tenant=TenantId(_TENANT),
        incident=IncidentId(_INCIDENT),
        run=RunId(_RUN),
        window=_window(),
        idempotency_key=key,
    )


def _proposal(*, signal: str = _SIGNAL, direction: str = "increase") -> str:
    return json.dumps(
        {
            "hypothesis_id": "h1",
            "tenant_id": _TENANT,
            "incident_id": _INCIDENT,
            "run_id": _RUN,
            "semantics": "descriptive",
            "composition": "all",
            "predicates": [
                {"predicate_id": "p1", "signal_key": signal, "expected_direction": direction}
            ],
        }
    )


class _StallingLLM:
    """An LLM client that never returns in time, to exercise the worker deadline."""

    async def propose_metric_hypotheses(self, request: HypothesisRequest) -> LLMProposal:
        await asyncio.sleep(30)
        return LLMProposal(raw_json="{}")


def _with_telemetry(source: InMemoryTelemetrySource) -> InMemoryTelemetrySource:
    source.set(TenantId(_TENANT), IncidentId(_INCIDENT), RunId(_RUN), _signals())
    return source


class _RecordingTelemetrySource:
    """Records what the worker passes, to pin the telemetry port contract (ADR 0017)."""

    def __init__(self, signals: Sequence[SignalBaselineInput]) -> None:
        self._signals = tuple(signals)
        self.calls: list[tuple[TenantId, IncidentId, RunId, IncidentWindow]] = []

    async def load(
        self, tenant: TenantId, incident: IncidentId, run: RunId, window: IncidentWindow
    ) -> tuple[SignalBaselineInput, ...]:
        self.calls.append((tenant, incident, run, window))
        return self._signals


class _PoisonTelemetrySource:
    """A port that fails with an *untyped* error, the shape that used to livelock the worker."""

    async def load(
        self, tenant: TenantId, incident: IncidentId, run: RunId, window: IncidentWindow
    ) -> tuple[SignalBaselineInput, ...]:
        raise RuntimeError("an unmapped infrastructure failure")


class TelemetryPortContractTest(unittest.IsolatedAsyncioTestCase):
    """A live source needs the incident window, so the worker must hand it over (ADR 0017)."""

    async def test_worker_passes_the_investigation_window_to_the_source(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        telemetry = _RecordingTelemetrySource(_signals())
        worker = Worker(factory, FakeLLMClient([_proposal()]), telemetry, worker_id="worker-1")

        await CreateInvestigation(factory).execute(_command())
        self.assertTrue(await worker.run_once())

        self.assertEqual(len(telemetry.calls), 1)
        tenant, incident, run, window = telemetry.calls[0]
        self.assertEqual(tenant, TenantId(_TENANT))
        self.assertEqual(incident, IncidentId(_INCIDENT))
        self.assertEqual(run, RunId(_RUN))
        self.assertEqual(window, _window())


class ApplicationPipelineTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_run_and_fetch_report(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        telemetry = _with_telemetry(InMemoryTelemetrySource())
        worker = Worker(factory, FakeLLMClient([_proposal()]), telemetry, worker_id="worker-1")

        investigation_id = await CreateInvestigation(factory).execute(_command())
        self.assertTrue(await worker.run_once())

        status = await GetInvestigationStatus(factory).execute(TenantId(_TENANT), investigation_id)
        self.assertEqual(status.status, InvestigationStatus.SUCCEEDED)

        report = await GetReport(factory).execute(TenantId(_TENANT), investigation_id)
        self.assertTrue(report.payload.strip())
        self.assertIsInstance(json.loads(report.payload), dict)
        assert report.baseline_payload is not None
        self.assertEqual(
            json.loads(report.baseline_payload)["schema_version"], "baseline-ranking.v1"
        )

        async with factory() as uow:
            evidence = await uow.evidence.list_for_investigation(
                TenantId(_TENANT), investigation_id
            )
        self.assertGreaterEqual(len(evidence), 1)

    async def test_run_once_returns_false_on_empty_queue(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        worker = Worker(factory, FakeLLMClient([]), InMemoryTelemetrySource(), worker_id="worker-1")
        self.assertFalse(await worker.run_once())

    async def test_report_not_ready_before_worker_runs(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation_id = await CreateInvestigation(factory).execute(_command())
        with self.assertRaises(ReportNotReadyError):
            await GetReport(factory).execute(TenantId(_TENANT), investigation_id)

    async def test_status_is_tenant_scoped(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        investigation_id = await CreateInvestigation(factory).execute(_command())
        with self.assertRaises(InvestigationNotFoundError):
            await GetInvestigationStatus(factory).execute(TenantId("tenant-b"), investigation_id)

    async def test_idempotent_create_enqueues_single_job(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        telemetry = _with_telemetry(InMemoryTelemetrySource())
        worker = Worker(factory, FakeLLMClient([_proposal()]), telemetry, worker_id="worker-1")
        create = CreateInvestigation(factory)
        first = await create.execute(_command(key="idem-1"))
        second = await create.execute(_command(key="idem-1"))
        self.assertEqual(first, second)
        self.assertTrue(await worker.run_once())
        self.assertFalse(await worker.run_once())

    async def test_malformed_proposal_fails_investigation(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        telemetry = _with_telemetry(InMemoryTelemetrySource())
        worker = Worker(factory, FakeLLMClient(["not-json"]), telemetry, worker_id="worker-1")
        investigation_id = await CreateInvestigation(factory).execute(_command())
        self.assertTrue(await worker.run_once())
        status = await GetInvestigationStatus(factory).execute(TenantId(_TENANT), investigation_id)
        self.assertEqual(status.status, InvestigationStatus.FAILED)
        with self.assertRaises(ReportNotReadyError):
            await GetReport(factory).execute(TenantId(_TENANT), investigation_id)

    async def test_unauthorized_signal_fails_investigation(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        telemetry = _with_telemetry(InMemoryTelemetrySource())
        worker = Worker(
            factory, FakeLLMClient([_proposal(signal="disk")]), telemetry, worker_id="worker-1"
        )
        investigation_id = await CreateInvestigation(factory).execute(_command())
        self.assertTrue(await worker.run_once())
        status = await GetInvestigationStatus(factory).execute(TenantId(_TENANT), investigation_id)
        self.assertEqual(status.status, InvestigationStatus.FAILED)

    async def test_missing_telemetry_fails_investigation(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        worker = Worker(
            factory, FakeLLMClient([_proposal()]), InMemoryTelemetrySource(), worker_id="worker-1"
        )
        investigation_id = await CreateInvestigation(factory).execute(_command())
        self.assertTrue(await worker.run_once())
        status = await GetInvestigationStatus(factory).execute(TenantId(_TENANT), investigation_id)
        self.assertEqual(status.status, InvestigationStatus.FAILED)

    async def test_poison_job_fails_closed_instead_of_being_reclaimed_forever(self) -> None:
        # The claim's attempt_count increment shares a transaction with the pipeline, so an
        # untyped escape rolled it back and returned the job to QUEUED unchanged: max_attempts
        # could never fire and the loop reclaimed the same job forever. It must fail closed.
        factory = InMemoryUnitOfWorkFactory()
        worker = Worker(
            factory, FakeLLMClient([_proposal()]), _PoisonTelemetrySource(), worker_id="worker-1"
        )
        investigation_id = await CreateInvestigation(factory).execute(_command())
        self.assertTrue(await worker.run_once())
        status = await GetInvestigationStatus(factory).execute(TenantId(_TENANT), investigation_id)
        self.assertEqual(status.status, InvestigationStatus.FAILED)
        # The queue is now empty: the poison job was not returned for another attempt.
        self.assertFalse(await worker.run_once())

    async def test_stalled_model_does_not_wedge_the_worker(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        telemetry = _with_telemetry(InMemoryTelemetrySource())
        worker = Worker(
            factory,
            _StallingLLM(),
            telemetry,
            worker_id="worker-1",
            deadline=timedelta(seconds=0.01),
            max_attempts=1,
        )
        investigation_id = await CreateInvestigation(factory).execute(_command())
        # Must return promptly (bounded by the deadline) rather than hang on the stalled model.
        self.assertTrue(await worker.run_once())
        status = await GetInvestigationStatus(factory).execute(TenantId(_TENANT), investigation_id)
        self.assertEqual(status.status, InvestigationStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
