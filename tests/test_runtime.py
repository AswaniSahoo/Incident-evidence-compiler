"""Hermetic tests for the Phase 9 runtime composition root and entrypoint.

Covers environment-only configuration parsing (fail-fast, secret-free), the labelled
non-model smoke LLM client, the labelled RCAEval demo telemetry source (against the
committed synthetic fixture, never real data), and the end-to-end wiring: a submitted
investigation is processed by the in-process worker into a persisted, verified report,
driven entirely through the runtime's own components. No network, database, or credentials.
"""

import asyncio
import unittest
from pathlib import Path

import httpx

from incident_evidence_compiler.application import TelemetryUnavailableError
from incident_evidence_compiler.domain.identifiers import IncidentId, RunId, TenantId
from incident_evidence_compiler.llm import HypothesisRequest, parse_metric_hypothesis
from incident_evidence_compiler.runtime import (
    AppConfig,
    ConfigError,
    FirstSignalLLMClient,
    RcaevalTelemetrySource,
    ServerComponents,
    build_components,
    create_server_app,
    run_worker_loop,
)

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "rcaeval" / "RE2-OB"
_TOKEN = "smoke-token"
_TENANT = "tenant-a"


def _base_env(**overrides: str) -> dict[str, str]:
    env = {"IEC_TOKENS": f"{_TOKEN}={_TENANT}"}
    env.update(overrides)
    return env


class ConfigTests(unittest.TestCase):
    def test_defaults_are_safe_and_credential_free(self) -> None:
        config = AppConfig.from_env(_base_env())
        self.assertEqual(config.persistence, "memory")
        self.assertEqual(config.llm_provider, "fake")
        self.assertEqual(config.telemetry, "none")
        self.assertEqual(config.bind_host, "127.0.0.1")
        self.assertEqual(config.bind_port, 8000)
        self.assertTrue(config.worker_enabled)
        self.assertEqual(config.tokens, {_TOKEN: _TENANT})

    def test_missing_tokens_is_fatal(self) -> None:
        with self.assertRaises(ConfigError):
            AppConfig.from_env({})

    def test_malformed_token_pair_is_fatal(self) -> None:
        for bad in ("no-equals", "=tenant", "token=", "a=b,=c"):
            with self.assertRaises(ConfigError):
                AppConfig.from_env({"IEC_TOKENS": bad})

    def test_postgres_requires_database_url(self) -> None:
        with self.assertRaises(ConfigError):
            AppConfig.from_env(_base_env(IEC_PERSISTENCE="postgres"))
        config = AppConfig.from_env(
            _base_env(IEC_PERSISTENCE="postgres", IEC_DATABASE_URL="postgresql://x/y")
        )
        self.assertEqual(config.database_url, "postgresql://x/y")

    def test_developer_provider_requires_api_key(self) -> None:
        with self.assertRaises(ConfigError):
            AppConfig.from_env(_base_env(IEC_LLM_PROVIDER="developer"))
        config = AppConfig.from_env(_base_env(IEC_LLM_PROVIDER="developer", GEMINI_API_KEY="k"))
        self.assertEqual(config.gemini_api_key, "k")

    def test_vertex_provider_requires_project_and_defaults_location(self) -> None:
        with self.assertRaises(ConfigError):
            AppConfig.from_env(_base_env(IEC_LLM_PROVIDER="vertex"))
        config = AppConfig.from_env(_base_env(IEC_LLM_PROVIDER="vertex", IEC_GEMINI_PROJECT="p"))
        self.assertEqual(config.gemini_project, "p")
        self.assertEqual(config.gemini_location, "us-central1")
        self.assertEqual(config.gemini_model, "gemini-2.5-flash")

    def test_rcaeval_telemetry_requires_root(self) -> None:
        with self.assertRaises(ConfigError):
            AppConfig.from_env(_base_env(IEC_TELEMETRY="rcaeval"))
        config = AppConfig.from_env(
            _base_env(IEC_TELEMETRY="rcaeval", IEC_RE2_ROOT=str(_FIXTURE_ROOT))
        )
        self.assertEqual(config.re2_root, _FIXTURE_ROOT)
        self.assertEqual(config.re2_split, "OB")

    def test_unknown_enumerated_values_are_fatal(self) -> None:
        for env in (
            _base_env(IEC_PERSISTENCE="mysql"),
            _base_env(IEC_LLM_PROVIDER="openai"),
            _base_env(IEC_TELEMETRY="kafka"),
            _base_env(IEC_BIND_PORT="not-a-port"),
            _base_env(IEC_BIND_PORT="0"),
            _base_env(IEC_WORKER_IDLE_SLEEP_SECONDS="-1"),
        ):
            with self.assertRaises(ConfigError):
                AppConfig.from_env(env)


class DemoLLMClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_proposes_parseable_hypothesis_over_first_allowed_signal(self) -> None:
        from incident_evidence_compiler.domain.metrics import SignalKey

        allowed_signals = frozenset({SignalKey("latency"), SignalKey("cpu")})
        request = HypothesisRequest(
            tenant=TenantId(_TENANT),
            incident=IncidentId("inc-1"),
            run=RunId("run-1"),
            allowed_signals=allowed_signals,
        )
        proposal = await FirstSignalLLMClient().propose_metric_hypotheses(request)
        document = parse_metric_hypothesis(proposal.raw_json, allowed_signals=allowed_signals)
        self.assertEqual(document.tenant_id, TenantId(_TENANT))
        self.assertEqual(len(document.predicates), 1)
        # Lexicographically-first allowed signal is chosen deterministically.
        self.assertEqual(document.predicates[0].signal_key, SignalKey("cpu"))


class RcaevalTelemetrySourceTests(unittest.IsolatedAsyncioTestCase):
    def test_indexes_fixture_cases_without_touching_ground_truth(self) -> None:
        source = RcaevalTelemetrySource(_FIXTURE_ROOT, split="OB")
        self.assertTrue(source.available)
        # Keys are the case directory paths (never a scored label object).
        self.assertTrue(any("CANARY" in key for key in source.available))

    async def test_load_returns_inputs_for_known_case_and_raises_for_unknown(self) -> None:
        source = RcaevalTelemetrySource(_FIXTURE_ROOT, split="OB")
        incident_key = next(key for key in source.available if "CANARY" in key)
        window = source.available[incident_key]
        # The window is part of the port (ADR 0017); a pre-indexed source accepts and ignores it.
        inputs = await source.load(
            TenantId(_TENANT), IncidentId(incident_key), RunId("run-1"), window
        )
        self.assertTrue(inputs)
        with self.assertRaises(TelemetryUnavailableError):
            await source.load(TenantId(_TENANT), IncidentId("no-such-case"), RunId("run-1"), window)


def _canary_incident(source: RcaevalTelemetrySource) -> str:
    return next(key for key in source.available if "CANARY" in key)


class BuildComponentsTests(unittest.IsolatedAsyncioTestCase):
    def _config(self) -> AppConfig:
        return AppConfig.from_env(
            _base_env(
                IEC_PERSISTENCE="memory",
                IEC_LLM_PROVIDER="fake",
                IEC_TELEMETRY="rcaeval",
                IEC_RE2_ROOT=str(_FIXTURE_ROOT),
            )
        )

    def test_build_components_returns_a_wired_system(self) -> None:
        components = build_components(self._config())
        self.assertIsInstance(components, ServerComponents)
        self.assertIsNotNone(components.worker)

    async def test_health_and_metrics_are_open(self) -> None:
        components = build_components(self._config())
        transport = httpx.ASGITransport(app=components.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/health")
            metrics = await client.get("/metrics")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(metrics.status_code, 200)

    async def test_end_to_end_investigation_yields_a_verified_report(self) -> None:
        config = self._config()
        components = build_components(config)
        assert isinstance(components.telemetry, RcaevalTelemetrySource)
        incident = _canary_incident(components.telemetry)
        window = components.telemetry.available[incident]

        transport = httpx.ASGITransport(app=components.app)
        headers = {"Authorization": f"Bearer {_TOKEN}"}
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/investigations",
                headers=headers,
                json={
                    "incident_id": incident,
                    "run_id": "run-1",
                    "window": {
                        "start": window.start.isoformat(),
                        "injection": window.injection.isoformat(),
                        "end": window.end.isoformat(),
                    },
                },
            )
            self.assertEqual(created.status_code, 202)

            assert components.worker is not None
            self.assertTrue(await components.worker.run_once())

            investigation_id = created.json()["investigation_id"]
            report = await client.get(f"/investigations/{investigation_id}/report", headers=headers)
        self.assertEqual(report.status_code, 200)
        # The CANARY fixture's cpu signal shifts up across the injection boundary, and the
        # smoke client proposes an increase on the first allowed signal (cpu) -> supported.
        self.assertEqual(report.json()["report"]["verdict"], "supported")


class WorkerLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_worker_loop_drains_queue_then_stops(self) -> None:
        config = AppConfig.from_env(
            _base_env(
                IEC_PERSISTENCE="memory",
                IEC_LLM_PROVIDER="fake",
                IEC_TELEMETRY="rcaeval",
                IEC_RE2_ROOT=str(_FIXTURE_ROOT),
                IEC_WORKER_IDLE_SLEEP_SECONDS="0.01",
            )
        )
        components = build_components(config)
        assert isinstance(components.telemetry, RcaevalTelemetrySource)
        assert components.worker is not None
        incident = _canary_incident(components.telemetry)
        window = components.telemetry.available[incident]

        transport = httpx.ASGITransport(app=components.app)
        headers = {"Authorization": f"Bearer {_TOKEN}"}
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/investigations",
                headers=headers,
                json={
                    "incident_id": incident,
                    "run_id": "run-1",
                    "window": {
                        "start": window.start.isoformat(),
                        "injection": window.injection.isoformat(),
                        "end": window.end.isoformat(),
                    },
                },
            )
            investigation_id = created.json()["investigation_id"]

            stop = asyncio.Event()
            task = asyncio.create_task(
                run_worker_loop(components.worker, stop_event=stop, idle_sleep_seconds=0.01)
            )
            report = None
            for _ in range(200):
                response = await client.get(
                    f"/investigations/{investigation_id}/report", headers=headers
                )
                if response.status_code == 200:
                    report = response.json()
                    break
                await asyncio.sleep(0.01)
            stop.set()
            await asyncio.wait_for(task, timeout=2.0)

        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(report["report"]["verdict"], "supported")


class ServerAppTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_server_app_serves_health(self) -> None:
        config = AppConfig.from_env(_base_env())
        app = create_server_app(config)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
