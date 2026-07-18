"""ASGI end-to-end tests for the control plane.

Hermetic: the FastAPI app is driven in-process via ``httpx.ASGITransport`` over the
in-memory persistence fake, with the worker run inline on a FakeLLMClient and in-memory
telemetry. No network, server, database, or credentials are required.
"""

import asyncio
import json
import unittest
from datetime import UTC, datetime, timedelta

import httpx

from incident_evidence_compiler.api import TokenRegistry, create_app
from incident_evidence_compiler.application import InMemoryTelemetrySource, Worker
from incident_evidence_compiler.domain.baseline import SignalBaselineInput
from incident_evidence_compiler.domain.identifiers import IncidentId, RunId, TenantId
from incident_evidence_compiler.domain.metrics import MetricPoint, MetricSignal, SignalKey
from incident_evidence_compiler.llm import FakeLLMClient, HypothesisRequest, LLMProposal
from incident_evidence_compiler.persistence import InMemoryUnitOfWorkFactory

_BASE = datetime(2026, 1, 1, tzinfo=UTC)
_TENANT = "tenant-a"
_INCIDENT = "inc-1"
_RUN = "run-1"
_SIGNAL = "cpu"
_TOKENS = {"tok-a": _TENANT, "tok-b": "tenant-b"}


def _window_payload() -> dict[str, str]:
    return {
        "start": _BASE.isoformat(),
        "injection": (_BASE + timedelta(minutes=10)).isoformat(),
        "end": (_BASE + timedelta(minutes=20)).isoformat(),
    }


def _create_body() -> dict[str, object]:
    return {"incident_id": _INCIDENT, "run_id": _RUN, "window": _window_payload()}


def _signals() -> list[SignalBaselineInput]:
    pre = [MetricPoint(_BASE + timedelta(minutes=i), 1.0) for i in range(3)]
    post = [MetricPoint(_BASE + timedelta(minutes=10 + i), 10.0) for i in range(3)]
    signal = MetricSignal(SignalKey(_SIGNAL), tuple(pre + post))
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
                {"predicate_id": "p1", "signal_key": _SIGNAL, "expected_direction": "increase"}
            ],
        }
    )


class _StallingLLM:
    async def propose_metric_hypotheses(self, request: HypothesisRequest) -> LLMProposal:
        await asyncio.sleep(30)
        return LLMProposal(raw_json="{}")


def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


class ControlPlaneTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.factory = InMemoryUnitOfWorkFactory()
        self.telemetry = InMemoryTelemetrySource()
        self.app = create_app(uow_factory=self.factory, tokens=TokenRegistry.from_mapping(_TOKENS))

    async def test_health_is_open(self) -> None:
        async with _client(self.app) as client:
            response = await client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    async def test_openapi_and_docs_are_not_exposed(self) -> None:
        async with _client(self.app) as client:
            openapi = await client.get("/openapi.json")
            docs = await client.get("/docs")
        self.assertEqual(openapi.status_code, 404)
        self.assertEqual(docs.status_code, 404)

    async def test_create_requires_a_valid_bearer_token(self) -> None:
        async with _client(self.app) as client:
            missing = await client.post("/investigations", json=_create_body())
            bad = await client.post(
                "/investigations",
                json=_create_body(),
                headers={"Authorization": "Bearer nope"},
            )
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(bad.status_code, 401)

    async def test_create_poll_and_fetch_report(self) -> None:
        self.telemetry.set(TenantId(_TENANT), IncidentId(_INCIDENT), RunId(_RUN), _signals())
        worker = Worker(
            self.factory, FakeLLMClient([_proposal()]), self.telemetry, worker_id="worker-1"
        )
        headers = {"Authorization": "Bearer tok-a"}
        async with _client(self.app) as client:
            created = await client.post("/investigations", json=_create_body(), headers=headers)
            self.assertEqual(created.status_code, 202)
            investigation_id = created.json()["investigation_id"]

            self.assertTrue(await worker.run_once())

            status = await client.get(f"/investigations/{investigation_id}", headers=headers)
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.json()["status"], "succeeded")

            report = await client.get(f"/investigations/{investigation_id}/report", headers=headers)
        self.assertEqual(report.status_code, 200)
        self.assertIsInstance(report.json()["report"], dict)

    async def test_idempotency_key_returns_same_investigation(self) -> None:
        headers = {"Authorization": "Bearer tok-a", "Idempotency-Key": "idem-1"}
        async with _client(self.app) as client:
            first = await client.post("/investigations", json=_create_body(), headers=headers)
            second = await client.post("/investigations", json=_create_body(), headers=headers)
        self.assertEqual(first.json()["investigation_id"], second.json()["investigation_id"])

    async def test_cross_tenant_access_returns_404(self) -> None:
        async with _client(self.app) as client:
            created = await client.post(
                "/investigations", json=_create_body(), headers={"Authorization": "Bearer tok-a"}
            )
            investigation_id = created.json()["investigation_id"]
            other = await client.get(
                f"/investigations/{investigation_id}", headers={"Authorization": "Bearer tok-b"}
            )
        self.assertEqual(other.status_code, 404)

    async def test_report_not_ready_returns_409(self) -> None:
        headers = {"Authorization": "Bearer tok-a"}
        async with _client(self.app) as client:
            created = await client.post("/investigations", json=_create_body(), headers=headers)
            investigation_id = created.json()["investigation_id"]
            report = await client.get(f"/investigations/{investigation_id}/report", headers=headers)
        self.assertEqual(report.status_code, 409)

    async def test_unknown_investigation_returns_404(self) -> None:
        headers = {"Authorization": "Bearer tok-a"}
        async with _client(self.app) as client:
            missing = await client.get(
                "/investigations/00000000-0000-4000-8000-000000000000", headers=headers
            )
            malformed = await client.get("/investigations/not-a-uuid", headers=headers)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(malformed.status_code, 404)

    async def test_invalid_window_returns_422(self) -> None:
        body = _create_body()
        body["window"] = {
            "start": _BASE.isoformat(),
            "injection": (_BASE - timedelta(minutes=1)).isoformat(),
            "end": (_BASE + timedelta(minutes=20)).isoformat(),
        }
        async with _client(self.app) as client:
            response = await client.post(
                "/investigations", json=body, headers={"Authorization": "Bearer tok-a"}
            )
        self.assertEqual(response.status_code, 422)

    async def test_health_stays_responsive_while_worker_is_stalled(self) -> None:
        self.telemetry.set(TenantId(_TENANT), IncidentId(_INCIDENT), RunId(_RUN), _signals())
        async with _client(self.app) as client:
            await client.post(
                "/investigations", json=_create_body(), headers={"Authorization": "Bearer tok-a"}
            )
            worker = Worker(
                self.factory,
                _StallingLLM(),
                self.telemetry,
                worker_id="worker-1",
                deadline=timedelta(seconds=30),
            )
            stalled = asyncio.create_task(worker.run_once())
            try:
                await asyncio.sleep(0)  # let the worker start and block on the stalled model
                response = await client.get("/health")
                self.assertEqual(response.status_code, 200)
            finally:
                stalled.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await stalled


if __name__ == "__main__":
    unittest.main()
