"""Hermetic tests for the Prometheus telemetry ingestion path (ADR 0017).

Covers the bounded range-query client, the series-to-signal mapper, and the telemetry source.
The client depends on an injected ``fetch`` callable rather than ``urllib`` directly, so it is
unit-testable with no network: the tests pass canned Prometheus API bodies and assert parsing,
bounds, typed failures, gap handling, and that the blocking fetch never runs on the event loop.
Nothing here opens a socket.
"""

import threading
import unittest
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from incident_evidence_compiler.application import TelemetryUnavailableError
from incident_evidence_compiler.domain.baseline import SignalBaselineInput
from incident_evidence_compiler.domain.identifiers import IncidentId, RunId, TenantId
from incident_evidence_compiler.domain.incidents import IncidentWindow
from incident_evidence_compiler.domain.metrics import SignalKey
from incident_evidence_compiler.runtime import AppConfig, ConfigError, build_components
from incident_evidence_compiler.runtime.prometheus import (
    PrometheusClient,
    PrometheusError,
    PrometheusLimits,
    PrometheusPoint,
    PrometheusSeries,
    PrometheusTelemetrySource,
    series_to_signals,
)

_START = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
_END = datetime(2024, 1, 1, 0, 1, tzinfo=UTC)
_WINDOW = IncidentWindow(
    start=_START, injection=_START + timedelta(seconds=30), end=_START + timedelta(minutes=2)
)

# A canonical Prometheus GET /api/v1/query_range success body: one matrix series with two samples.
_SUCCESS = (
    b'{"status":"success","data":{"resultType":"matrix","result":['
    b'{"metric":{"__name__":"http_latency_seconds","service":"checkout"},'
    b'"values":[[1704067200,"1.5"],[1704067260,"2.5"]]}]}}'
)


class _FakeFetch:
    """Records calls and returns a fixed ``(status, body)``."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def __call__(self, url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
        self.calls.append((url, headers, timeout))
        return self.status, self.body


class PrometheusClientParseTests(unittest.TestCase):
    def test_range_query_parses_series_and_points(self) -> None:
        fetch = _FakeFetch(200, _SUCCESS)
        client = PrometheusClient("http://prom:9090", fetch=fetch)

        series = client.query_range(
            "http_latency_seconds",
            start=_START,
            end=_END,
            step_seconds=60,
            deadline=timedelta(seconds=30),
        )

        self.assertEqual(len(series), 1)
        one = series[0]
        self.assertIsInstance(one, PrometheusSeries)
        self.assertEqual(one.name, 'http_latency_seconds{service="checkout"}')
        self.assertEqual(len(one.points), 2)
        self.assertEqual(one.points[0].value, 1.5)
        self.assertEqual(one.points[0].at, datetime(2024, 1, 1, 0, 0, tzinfo=UTC))
        self.assertEqual(one.points[1].value, 2.5)


class PrometheusClientFailureTests(unittest.TestCase):
    """Every non-happy path raises a stable, message-free ``PrometheusError``."""

    def _query(self, status: int, body: bytes) -> None:
        client = PrometheusClient("http://prom:9090", fetch=_FakeFetch(status, body))
        client.query_range(
            "up", start=_START, end=_END, step_seconds=60, deadline=timedelta(seconds=5)
        )

    def test_non_2xx_status_raises(self) -> None:
        with self.assertRaises(PrometheusError):
            self._query(503, b'{"status":"success","data":{"result":[]}}')

    def test_api_error_status_raises(self) -> None:
        with self.assertRaises(PrometheusError):
            self._query(200, b'{"status":"error","errorType":"bad_data","error":"whatever"}')

    def test_malformed_body_raises(self) -> None:
        with self.assertRaises(PrometheusError):
            self._query(200, b"this is not json")

    def test_missing_result_shape_raises(self) -> None:
        with self.assertRaises(PrometheusError):
            self._query(200, b'{"status":"success","data":{}}')


class PrometheusClientBoundsTests(unittest.TestCase):
    """The client refuses responses that exceed its bounds rather than allocate unboundedly."""

    def _client(self, body: bytes, limits: PrometheusLimits) -> PrometheusClient:
        return PrometheusClient("http://prom:9090", fetch=_FakeFetch(200, body), limits=limits)

    def test_oversized_body_raises(self) -> None:
        client = self._client(_SUCCESS, PrometheusLimits(max_response_bytes=10))
        with self.assertRaises(PrometheusError):
            client.query_range(
                "up", start=_START, end=_END, step_seconds=60, deadline=timedelta(seconds=5)
            )

    def test_too_many_series_raises(self) -> None:
        two = (
            b'{"status":"success","data":{"resultType":"matrix","result":['
            b'{"metric":{"__name__":"a"},"values":[[1704067200,"1"]]},'
            b'{"metric":{"__name__":"b"},"values":[[1704067200,"1"]]}]}}'
        )
        client = self._client(two, PrometheusLimits(max_series=1))
        with self.assertRaises(PrometheusError):
            client.query_range(
                "up", start=_START, end=_END, step_seconds=60, deadline=timedelta(seconds=5)
            )

    def test_too_many_points_raises(self) -> None:
        client = self._client(_SUCCESS, PrometheusLimits(max_points_per_series=1))
        with self.assertRaises(PrometheusError):
            client.query_range(
                "up", start=_START, end=_END, step_seconds=60, deadline=timedelta(seconds=5)
            )


class SeriesToSignalsTests(unittest.TestCase):
    """Prometheus series map to domain signals, dropping non-finite samples (ADR 0010)."""

    def test_maps_series_and_drops_non_finite_points(self) -> None:
        series = (
            PrometheusSeries(
                'http_latency_seconds{service="checkout"}',
                (
                    PrometheusPoint(datetime(2024, 1, 1, 0, 0, tzinfo=UTC), 1.0),
                    PrometheusPoint(datetime(2024, 1, 1, 0, 1, tzinfo=UTC), float("nan")),
                    PrometheusPoint(datetime(2024, 1, 1, 0, 2, tzinfo=UTC), 2.0),
                ),
            ),
        )

        signals = series_to_signals(series)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].key, SignalKey('http_latency_seconds{service="checkout"}'))
        self.assertEqual([point.value for point in signals[0].points], [1.0, 2.0])

    def test_series_with_no_finite_points_is_dropped(self) -> None:
        series = (
            PrometheusSeries(
                "all_gaps",
                (PrometheusPoint(datetime(2024, 1, 1, tzinfo=UTC), float("inf")),),
            ),
        )
        self.assertEqual(series_to_signals(series), ())

    def test_unnameable_series_fails_closed(self) -> None:
        # A series with neither __name__ nor labels renders an empty name, which cannot be
        # cited as evidence; that is a malformed response, not a gap.
        series = (PrometheusSeries("", (PrometheusPoint(_START, 1.0),)),)
        with self.assertRaises(PrometheusError):
            series_to_signals(series)

    def test_non_monotonic_samples_fail_closed(self) -> None:
        # Sorting or de-duplicating here would silently forge a timeline the server never sent.
        series = (
            PrometheusSeries("cpu", (PrometheusPoint(_END, 1.0), PrometheusPoint(_START, 2.0))),
        )
        with self.assertRaises(PrometheusError):
            series_to_signals(series)

    def test_duplicate_series_names_fail_closed(self) -> None:
        # Two signals under one key raise DuplicateSignalError inside the baseline; rejecting
        # it here attributes the failure to telemetry, where it originated.
        series = (
            PrometheusSeries("cpu", (PrometheusPoint(_START, 1.0),)),
            PrometheusSeries("cpu", (PrometheusPoint(_START, 2.0),)),
        )
        with self.assertRaises(PrometheusError):
            series_to_signals(series)


class PrometheusClientFactoryTests(unittest.TestCase):
    def test_over_http_builds_a_client_without_opening_a_socket(self) -> None:
        # The factory only wires a urllib-backed fetch; constructing it touches no network.
        client = PrometheusClient.over_http("http://prom:9090/", bearer_token="secret")
        self.assertIsInstance(client, PrometheusClient)


class _ThreadRecordingFetch(_FakeFetch):
    """A fetch that also records which OS thread performed the blocking call."""

    def __init__(self, status: int, body: bytes) -> None:
        super().__init__(status, body)
        self.thread_idents: list[int] = []

    def __call__(self, url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
        self.thread_idents.append(threading.get_ident())
        return super().__call__(url, headers, timeout)


class PrometheusTelemetrySourceTests(unittest.IsolatedAsyncioTestCase):
    """The source range-queries the incident window, off the event loop, and fails closed."""

    def _source(self, fetch: _FakeFetch, *queries: str) -> PrometheusTelemetrySource:
        client = PrometheusClient("http://prom:9090", fetch=fetch)
        return PrometheusTelemetrySource(
            client,
            queries or ("http_latency_seconds",),
            step_seconds=60,
            deadline=timedelta(seconds=5),
        )

    async def _load(self, source: PrometheusTelemetrySource) -> tuple[SignalBaselineInput, ...]:
        return await source.load(TenantId("tenant-a"), IncidentId("inc-1"), RunId("run-1"), _WINDOW)

    async def test_load_returns_baseline_inputs_over_the_window(self) -> None:
        fetch = _FakeFetch(200, _SUCCESS)
        inputs = await self._load(self._source(fetch))

        self.assertEqual(len(inputs), 1)
        self.assertEqual(
            inputs[0].signal.key, SignalKey('http_latency_seconds{service="checkout"}')
        )
        # The baseline requires a strictly-positive floor; the source must derive one.
        self.assertGreater(inputs[0].absolute_scale_floor, 0.0)
        # The queried range is the incident window, not a hardcoded lookback.
        url = fetch.calls[0][0]
        self.assertIn(f"start={_WINDOW.start.timestamp():.3f}", url)
        self.assertIn(f"end={_WINDOW.end.timestamp():.3f}", url)

    async def test_every_configured_query_is_issued(self) -> None:
        fetch = _FakeFetch(200, _SUCCESS)
        # Two selectors returning the same series name must fail closed, not silently merge.
        with self.assertRaises(TelemetryUnavailableError):
            await self._load(self._source(fetch, "one", "two"))
        self.assertEqual(len(fetch.calls), 2)

    async def test_transport_failure_becomes_telemetry_unavailable(self) -> None:
        for status, body in ((503, _SUCCESS), (200, b"not json")):
            with self.subTest(status=status):
                with self.assertRaises(TelemetryUnavailableError):
                    await self._load(self._source(_FakeFetch(status, body)))

    async def test_blocking_fetch_runs_off_the_event_loop(self) -> None:
        fetch = _ThreadRecordingFetch(200, _SUCCESS)
        await self._load(self._source(fetch))
        self.assertEqual(len(fetch.thread_idents), 1)
        # Blocking urllib on the worker's event loop would stall every other task.
        self.assertNotEqual(fetch.thread_idents[0], threading.get_ident())

    def test_construction_rejects_an_empty_or_invalid_configuration(self) -> None:
        client = PrometheusClient("http://prom:9090", fetch=_FakeFetch(200, _SUCCESS))
        with self.assertRaises(ValueError):
            PrometheusTelemetrySource(client, ())
        with self.assertRaises(ValueError):
            PrometheusTelemetrySource(client, ("   ",))
        with self.assertRaises(ValueError):
            PrometheusTelemetrySource(client, ("up",), step_seconds=0)
        with self.assertRaises(ValueError):
            PrometheusTelemetrySource(client, ("up",), deadline=timedelta(0))


class PrometheusConfigTests(unittest.TestCase):
    """``IEC_TELEMETRY=prometheus`` config is fail-fast and never echoes the credential."""

    @staticmethod
    def _env(**overrides: str) -> dict[str, str]:
        env = {"IEC_TOKENS": "smoke-token=tenant-a", "IEC_TELEMETRY": "prometheus"}
        env.update(overrides)
        return env

    def test_url_and_queries_are_required(self) -> None:
        with self.assertRaises(ConfigError):
            AppConfig.from_env(self._env())
        with self.assertRaises(ConfigError):
            AppConfig.from_env(self._env(IEC_PROM_URL="http://prom:9090"))

    def test_selectors_are_semicolon_separated_so_promql_commas_survive(self) -> None:
        config = AppConfig.from_env(
            self._env(
                IEC_PROM_URL="http://prom:9090",
                IEC_PROM_QUERIES='rate(http_requests_total{code="500",job="api"}[5m]) ; up',
            )
        )
        self.assertEqual(config.prom_url, "http://prom:9090")
        self.assertEqual(
            config.prom_queries,
            ('rate(http_requests_total{code="500",job="api"}[5m])', "up"),
        )
        self.assertEqual(config.prom_step_seconds, 30)
        self.assertEqual(config.prom_timeout_seconds, 30.0)
        self.assertIsNone(config.prom_bearer_token)

    def test_numeric_knobs_are_validated(self) -> None:
        for bad in (
            {"IEC_PROM_STEP_SECONDS": "0"},
            {"IEC_PROM_STEP_SECONDS": "not-a-number"},
            {"IEC_PROM_TIMEOUT_SECONDS": "-1"},
            {"IEC_PROM_TIMEOUT_SECONDS": "not-a-number"},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ConfigError):
                    AppConfig.from_env(
                        self._env(IEC_PROM_URL="http://prom:9090", IEC_PROM_QUERIES="up", **bad)
                    )

    def test_bearer_token_is_never_echoed_in_an_error(self) -> None:
        with self.assertRaises(ConfigError) as caught:
            AppConfig.from_env(self._env(IEC_PROM_BEARER_TOKEN="super-secret"))
        self.assertNotIn("super-secret", str(caught.exception))

    def test_source_is_wired_without_opening_a_socket(self) -> None:
        config = AppConfig.from_env(
            self._env(
                IEC_PROM_URL="http://prom:9090",
                IEC_PROM_QUERIES="up",
                IEC_PROM_BEARER_TOKEN="secret",
            )
        )
        self.assertIsInstance(build_components(config).telemetry, PrometheusTelemetrySource)


def _serve_canned(
    body: bytes, status: int = 200
) -> tuple[HTTPServer, list[tuple[str, str | None]]]:
    """Start a loopback HTTP server on an ephemeral port, recording (path, auth) per request."""
    seen: list[tuple[str, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append((self.path, self.headers.get("Authorization")))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return  # keep the test output clean

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


class PrometheusOverHttpSocketTests(unittest.IsolatedAsyncioTestCase):
    """The real ``urllib`` transport against a real socket, a loopback stub, not a Prometheus.

    Every other test injects ``fetch``, so this is the only place ``over_http``'s actual HTTP
    path runs: URL construction, the bearer header, status handling, and body reading.
    """

    def _url(self, body: bytes, status: int = 200) -> tuple[str, list[tuple[str, str | None]]]:
        server, seen = _serve_canned(body, status)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        # Bound to 127.0.0.1 above, so only the ephemeral port has to be discovered.
        return f"http://127.0.0.1:{server.server_address[1]}", seen

    def test_query_range_over_a_live_socket_sends_the_bearer_header(self) -> None:
        base_url, seen = self._url(_SUCCESS)
        client = PrometheusClient.over_http(base_url, bearer_token="demo-token")

        series = client.query_range(
            "up", start=_START, end=_END, step_seconds=60, deadline=timedelta(seconds=5)
        )

        self.assertEqual(len(series), 1)
        self.assertEqual(series[0].name, 'http_latency_seconds{service="checkout"}')
        path, auth = seen[0]
        self.assertIn("/api/v1/query_range?", path)
        self.assertEqual(auth, "Bearer demo-token")

    def test_non_2xx_over_a_live_socket_raises(self) -> None:
        base_url, _ = self._url(b'{"status":"error"}', status=503)
        client = PrometheusClient.over_http(base_url)
        with self.assertRaises(PrometheusError):
            client.query_range(
                "up", start=_START, end=_END, step_seconds=60, deadline=timedelta(seconds=5)
            )

    async def test_the_source_loads_over_a_live_socket(self) -> None:
        base_url, seen = self._url(_SUCCESS)
        source = PrometheusTelemetrySource(
            PrometheusClient.over_http(base_url), ("up",), step_seconds=60
        )

        inputs = await source.load(
            TenantId("tenant-a"), IncidentId("inc-1"), RunId("run-1"), _WINDOW
        )

        self.assertEqual(len(inputs), 1)
        self.assertEqual(len(seen), 1)


if __name__ == "__main__":
    unittest.main()
