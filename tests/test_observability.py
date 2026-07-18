"""Hermetic tests for Phase 8 observability (Prometheus-style metrics).

Covers the dependency-free registry's exposition format, that the worker records job
outcomes / verdict / stage latency into a shared registry, and that the control plane's
open ``/metrics`` endpoint renders it. No network, database, or credentials.
"""

import json
import unittest
from datetime import UTC, datetime, timedelta

import httpx

from incident_evidence_compiler.api import TokenRegistry, create_app
from incident_evidence_compiler.application import (
    CreateInvestigation,
    CreateInvestigationCommand,
    InMemoryTelemetrySource,
    Worker,
)
from incident_evidence_compiler.domain.baseline import SignalBaselineInput
from incident_evidence_compiler.domain.identifiers import IncidentId, RunId, TenantId
from incident_evidence_compiler.domain.incidents import IncidentWindow
from incident_evidence_compiler.domain.metrics import MetricPoint, MetricSignal, SignalKey
from incident_evidence_compiler.llm import FakeLLMClient, HypothesisRequest, LLMProposal
from incident_evidence_compiler.observability import Histogram, MetricsRegistry
from incident_evidence_compiler.persistence import InMemoryUnitOfWorkFactory

_TENANT = "tenant-a"
_INCIDENT = "inc-1"
_RUN = "run-1"
_BASE = datetime(2026, 1, 1, tzinfo=UTC)


class MetricsRegistryTests(unittest.TestCase):
    def test_counter_renders_labelled_series(self) -> None:
        registry = MetricsRegistry()
        counter = registry.counter("iec_thing_total", "A thing.", ("kind",))
        counter.inc(labels=("a",))
        counter.inc(2.0, labels=("a",))
        counter.inc(labels=("b",))
        out = registry.render()
        self.assertIn("# TYPE iec_thing_total counter", out)
        self.assertIn('iec_thing_total{kind="a"} 3', out)
        self.assertIn('iec_thing_total{kind="b"} 1', out)

    def test_counter_rejects_decrease_and_bad_label_arity(self) -> None:
        counter = MetricsRegistry().counter("iec_x_total", "x", ("k",))
        with self.assertRaises(ValueError):
            counter.inc(-1.0, labels=("a",))
        with self.assertRaises(ValueError):
            counter.inc(labels=())

    def test_histogram_buckets_are_cumulative_with_sum_and_count(self) -> None:
        histogram = Histogram("iec_lat_seconds", "Latency.", buckets=(0.1, 1.0), labelnames=("s",))
        histogram.observe(0.1, labels=("x",))  # <= 0.1 and <= 1.0
        histogram.observe(1.0, labels=("x",))  # <= 1.0 only
        histogram.observe(5.0, labels=("x",))  # neither finite bucket
        registry = MetricsRegistry()
        registry_histogram = registry.histogram(
            "iec_lat_seconds", "Latency.", buckets=(0.1, 1.0), labelnames=("s",)
        )
        for value in (0.1, 1.0, 5.0):
            registry_histogram.observe(value, labels=("x",))
        out = registry.render()
        self.assertIn("# TYPE iec_lat_seconds histogram", out)
        self.assertIn('iec_lat_seconds_bucket{s="x",le="0.1"} 1', out)
        self.assertIn('iec_lat_seconds_bucket{s="x",le="1"} 2', out)
        self.assertIn('iec_lat_seconds_bucket{s="x",le="+Inf"} 3', out)
        self.assertIn('iec_lat_seconds_count{s="x"} 3', out)

    def test_registry_registration_is_idempotent(self) -> None:
        registry = MetricsRegistry()
        first = registry.counter("iec_dup_total", "dup")
        second = registry.counter("iec_dup_total", "dup")
        self.assertIs(first, second)

    def test_timer_records_an_observation(self) -> None:
        histogram = Histogram("iec_t_seconds", "t", buckets=(1.0,))
        with histogram.time():
            pass
        self.assertIn("iec_t_seconds_count 1", "\n".join(histogram._render_lines()))


def _window() -> IncidentWindow:
    return IncidentWindow(
        start=_BASE, injection=_BASE + timedelta(minutes=10), end=_BASE + timedelta(minutes=20)
    )


def _signals() -> list[SignalBaselineInput]:
    pre = [MetricPoint(_BASE + timedelta(minutes=i), 1.0) for i in range(3)]
    post = [MetricPoint(_BASE + timedelta(minutes=10 + i), 10.0) for i in range(3)]
    signal = MetricSignal(SignalKey("cpu"), tuple(pre + post))
    return [SignalBaselineInput(signal=signal, absolute_scale_floor=1.0)]


def _proposal() -> str:
    return json.dumps(
        {
            "hypothesis_id": "h1",
            "tenant_id": _TENANT,
            "incident_id": _INCIDENT,
            "run_id": _RUN,
            "semantics": "descriptive",
            "composition": "all",
            "predicates": [
                {"predicate_id": "p1", "signal_key": "cpu", "expected_direction": "increase"}
            ],
        }
    )


def _command() -> CreateInvestigationCommand:
    return CreateInvestigationCommand(
        tenant=TenantId(_TENANT), incident=IncidentId(_INCIDENT), run=RunId(_RUN), window=_window()
    )


class _FixedProposalClient:
    """An ``LLMClient`` that returns one configured proposal (to carry token metadata)."""

    def __init__(self, proposal: LLMProposal) -> None:
        self._proposal = proposal

    async def propose_metric_hypotheses(self, request: HypothesisRequest) -> LLMProposal:
        return self._proposal


class WorkerMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_run_records_outcome_verdict_and_stage_metrics(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        telemetry = InMemoryTelemetrySource()
        telemetry.set(TenantId(_TENANT), IncidentId(_INCIDENT), RunId(_RUN), _signals())
        registry = MetricsRegistry()
        worker = Worker(
            factory, FakeLLMClient([_proposal()]), telemetry, worker_id="w1", metrics=registry
        )
        await CreateInvestigation(factory).execute(_command())
        self.assertTrue(await worker.run_once())

        out = registry.render()
        self.assertIn('iec_worker_jobs_total{outcome="succeeded"} 1', out)
        self.assertIn('iec_investigation_verdicts_total{verdict="supported"} 1', out)
        self.assertIn('iec_worker_stage_duration_seconds_count{stage="llm_propose"} 1', out)
        self.assertIn('iec_worker_stage_duration_seconds_count{stage="persist"} 1', out)

    async def test_missing_telemetry_records_failed_outcome(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        registry = MetricsRegistry()
        worker = Worker(
            factory,
            FakeLLMClient([_proposal()]),
            InMemoryTelemetrySource(),
            worker_id="w1",
            metrics=registry,
        )
        await CreateInvestigation(factory).execute(_command())
        self.assertTrue(await worker.run_once())
        self.assertIn('iec_worker_jobs_total{outcome="failed"} 1', registry.render())

    async def test_positive_token_counts_are_recorded(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        telemetry = InMemoryTelemetrySource()
        telemetry.set(TenantId(_TENANT), IncidentId(_INCIDENT), RunId(_RUN), _signals())
        registry = MetricsRegistry()
        client = _FixedProposalClient(
            LLMProposal(raw_json=_proposal(), prompt_tokens=12, completion_tokens=7)
        )
        worker = Worker(factory, client, telemetry, worker_id="w1", metrics=registry)
        await CreateInvestigation(factory).execute(_command())
        self.assertTrue(await worker.run_once())

        out = registry.render()
        self.assertIn('iec_llm_tokens_total{kind="prompt"} 12', out)
        self.assertIn('iec_llm_tokens_total{kind="completion"} 7', out)

    async def test_hostile_non_positive_token_counts_do_not_crash_or_emit(self) -> None:
        # Token counts are untrusted provider metadata; a negative/zero value must not
        # reach the counter (which would raise and escape the typed-failure contract).
        factory = InMemoryUnitOfWorkFactory()
        telemetry = InMemoryTelemetrySource()
        telemetry.set(TenantId(_TENANT), IncidentId(_INCIDENT), RunId(_RUN), _signals())
        registry = MetricsRegistry()
        client = _FixedProposalClient(
            LLMProposal(raw_json=_proposal(), prompt_tokens=-5, completion_tokens=0)
        )
        worker = Worker(factory, client, telemetry, worker_id="w1", metrics=registry)
        await CreateInvestigation(factory).execute(_command())
        self.assertTrue(await worker.run_once())

        out = registry.render()
        self.assertIn('iec_worker_jobs_total{outcome="succeeded"} 1', out)
        # The counter family is registered at worker init (HELP/TYPE always render), but
        # no prompt/completion series must be emitted for non-positive counts.
        self.assertNotIn("iec_llm_tokens_total{kind=", out)


class MetricsEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_metrics_endpoint_is_open_and_renders_registry(self) -> None:
        factory = InMemoryUnitOfWorkFactory()
        telemetry = InMemoryTelemetrySource()
        telemetry.set(TenantId(_TENANT), IncidentId(_INCIDENT), RunId(_RUN), _signals())
        registry = MetricsRegistry()
        app = create_app(
            uow_factory=factory,
            tokens=TokenRegistry.from_mapping({"tok-a": _TENANT}),
            metrics=registry,
        )
        worker = Worker(
            factory, FakeLLMClient([_proposal()]), telemetry, worker_id="w1", metrics=registry
        )
        await CreateInvestigation(factory).execute(_command())
        self.assertTrue(await worker.run_once())

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers["content-type"])
        self.assertIn("iec_worker_jobs_total", response.text)
        self.assertIn("iec_worker_stage_duration_seconds_bucket", response.text)


if __name__ == "__main__":
    unittest.main()
