"""Hermetic tests for the bounded Prometheus range-query client (ADR 0017).

The client depends on an injected ``fetch`` callable rather than ``urllib`` directly, so it is
unit-testable with no network: the tests pass canned Prometheus API bodies and assert parsing,
bounds, and typed failures. Nothing here opens a socket.
"""

import unittest
from datetime import UTC, datetime, timedelta

from incident_evidence_compiler.runtime.prometheus import (
    PrometheusClient,
    PrometheusError,
    PrometheusLimits,
    PrometheusSeries,
)

_START = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
_END = datetime(2024, 1, 1, 0, 1, tzinfo=UTC)

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


class PrometheusClientFactoryTests(unittest.TestCase):
    def test_over_http_builds_a_client_without_opening_a_socket(self) -> None:
        # The factory only wires a urllib-backed fetch; constructing it touches no network.
        client = PrometheusClient.over_http("http://prom:9090/", bearer_token="secret")
        self.assertIsInstance(client, PrometheusClient)


if __name__ == "__main__":
    unittest.main()
