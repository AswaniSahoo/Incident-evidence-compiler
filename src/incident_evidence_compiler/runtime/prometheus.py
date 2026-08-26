"""A bounded Prometheus range-query client (ADR 0017), standard-library only.

The client talks to Prometheus' ``GET /api/v1/query_range`` HTTP+JSON API. It depends on an
injected ``fetch`` callable, ``(url, headers, timeout_seconds) -> (status, body)``, rather than
``urllib`` directly, so it is unit-testable with no network and the transport coupling is confined
to one adapter. The parsed response is untrusted input: every non-happy path (transport status,
malformed body, unexpected shape, or a bound breach) raises a stable, message-free
``PrometheusError`` rather than leaking a response body or allocating unboundedly. A later slice
maps these series onto the domain metric model.
"""

import asyncio
import json
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from ..application import TelemetryUnavailableError
from ..domain.baseline import SignalBaselineInput
from ..domain.errors import DomainError
from ..domain.identifiers import IncidentId, RunId, TenantId
from ..domain.incidents import IncidentWindow
from ..domain.metrics import MetricPoint, MetricSignal, SignalKey
from ..evaluation.harness.baseline_inputs import ScaleFloorPolicy, to_baseline_inputs

Fetch = Callable[[str, dict[str, str], float], tuple[int, bytes]]


class PrometheusError(Exception):
    """A stable, message-free failure querying Prometheus (transport, shape, or bounds)."""


@dataclass(frozen=True, slots=True)
class PrometheusLimits:
    max_response_bytes: int = 8_388_608
    max_series: int = 2_048
    max_points_per_series: int = 100_000

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for field in fields(self)
            if (value := getattr(self, field.name)) is not None
        ):
            raise ValueError("invalid_prometheus_limits")


@dataclass(frozen=True, slots=True)
class PrometheusPoint:
    at: datetime
    value: float


@dataclass(frozen=True, slots=True)
class PrometheusSeries:
    name: str
    points: tuple[PrometheusPoint, ...]


def _series_name(metric: dict[str, Any]) -> str:
    """Render a stable series name: ``metric_name{label="value",...}`` with labels sorted."""
    base = str(metric.get("__name__", ""))
    labels = sorted((k, str(v)) for k, v in metric.items() if k != "__name__")
    if not labels:
        return base
    inner = ",".join(f'{key}="{value}"' for key, value in labels)
    return f"{base}{{{inner}}}"


class PrometheusClient:
    """Query a Prometheus range endpoint through an injected ``fetch`` transport."""

    def __init__(
        self,
        base_url: str,
        *,
        fetch: Fetch,
        limits: PrometheusLimits | None = None,
        bearer_token: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._fetch = fetch
        self._limits = limits if limits is not None else PrometheusLimits()
        self._bearer_token = bearer_token

    @classmethod
    def over_http(
        cls,
        base_url: str,
        *,
        limits: PrometheusLimits | None = None,
        bearer_token: str | None = None,
    ) -> "PrometheusClient":
        """Build a client whose transport is the standard-library ``urllib`` (no dependency).

        The read is bounded to one byte past the response-size limit so an over-large body is
        rejected without being fully buffered. Constructing this opens no socket; the network
        call happens only on ``query_range``.
        """
        resolved = limits if limits is not None else PrometheusLimits()
        max_read = resolved.max_response_bytes + 1

        def fetch(url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
            import urllib.request

            request = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return int(response.status), response.read(max_read)

        return cls(base_url, fetch=fetch, limits=resolved, bearer_token=bearer_token)

    def query_range(
        self,
        query: str,
        *,
        start: datetime,
        end: datetime,
        step_seconds: int,
        deadline: timedelta,
    ) -> tuple[PrometheusSeries, ...]:
        params = urlencode(
            {
                "query": query,
                "start": f"{start.timestamp():.3f}",
                "end": f"{end.timestamp():.3f}",
                "step": f"{step_seconds}s",
            }
        )
        url = f"{self._base_url}/api/v1/query_range?{params}"
        headers: dict[str, str] = {}
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"

        try:
            status, body = self._fetch(url, headers, deadline.total_seconds())
        except Exception as error:
            raise PrometheusError from error
        if not 200 <= status < 300:
            raise PrometheusError
        if len(body) > self._limits.max_response_bytes:
            raise PrometheusError
        return _parse_range_response(body, self._limits)


def _parse_range_response(body: bytes, limits: PrometheusLimits) -> tuple[PrometheusSeries, ...]:
    try:
        document = json.loads(body)
    except ValueError as error:
        raise PrometheusError from error
    if not isinstance(document, dict) or document.get("status") != "success":
        raise PrometheusError
    data = document.get("data")
    if not isinstance(data, dict):
        raise PrometheusError
    result = data.get("result")
    if not isinstance(result, list):
        raise PrometheusError
    if len(result) > limits.max_series:
        raise PrometheusError

    series: list[PrometheusSeries] = []
    for item in result:
        if not isinstance(item, dict):
            raise PrometheusError
        metric = item.get("metric")
        values = item.get("values")
        if not isinstance(metric, dict) or not isinstance(values, list):
            raise PrometheusError
        if len(values) > limits.max_points_per_series:
            raise PrometheusError
        points: list[PrometheusPoint] = []
        for sample in values:
            try:
                raw_ts, raw_value = sample
                at = datetime.fromtimestamp(float(raw_ts), tz=UTC)
                value = float(raw_value)
            except (TypeError, ValueError, OverflowError, OSError) as error:
                raise PrometheusError from error
            points.append(PrometheusPoint(at, value))
        series.append(PrometheusSeries(_series_name(metric), tuple(points)))
    return tuple(series)


def series_to_signals(series: Iterable[PrometheusSeries]) -> tuple[MetricSignal, ...]:
    """Map Prometheus series onto domain metric signals, dropping non-finite samples.

    Prometheus renders staleness and division artefacts as ``NaN``/``±Inf``. Those samples are
    *gaps*: the point is dropped rather than coerced to zero, and a series left with no finite
    point is dropped entirely (ADR 0010). What is not a gap is a response the domain cannot
    represent, an unnameable series, non-monotonic samples, or two series rendering one key
    (which ``rank_metric_shifts`` rejects as ``DuplicateSignalError``). Those raise
    ``PrometheusError`` so the caller fails closed rather than analyzing a repaired timeline.
    """
    signals: list[MetricSignal] = []
    seen: set[str] = set()
    for one in series:
        finite = tuple(sample for sample in one.points if math.isfinite(sample.value))
        if not finite:
            continue
        # Only an emitted signal can collide; a fully-dropped series reserves no key.
        if one.name in seen:
            raise PrometheusError
        seen.add(one.name)
        try:
            signals.append(
                MetricSignal(
                    SignalKey(one.name),
                    tuple(MetricPoint(sample.at, sample.value) for sample in finite),
                )
            )
        except DomainError as error:
            raise PrometheusError from error
    return tuple(signals)


class PrometheusTelemetrySource:
    """Range-query a live Prometheus over the incident window (ADR 0017).

    Read-only ingestion: every configured PromQL selector is range-queried across
    ``[window.start, window.end]``, and the returned series become domain signals wrapped with a
    derived scale floor, so the baseline behaves exactly as it does for any other source.

    Three boundary properties matter. The ``urllib`` fetch is blocking, so ``load`` hands the
    whole query-and-map step to a worker thread rather than stalling the worker's event loop.
    Every typed failure, deadline, transport, non-2xx, malformed body, bound breach, or a
    response the domain cannot represent, becomes ``TelemetryUnavailableError``, which the
    worker already treats as a terminal, leakage-safe failure. And the deadline is *per query*,
    so a configuration with many selectors must size it accordingly.

    The selectors are process configuration, not per-incident state, so one process serves one
    Prometheus and every tenant it authenticates sees the same telemetry. Per-incident,
    per-tenant queries are deferred future work (ADR 0017).
    """

    def __init__(
        self,
        client: PrometheusClient,
        queries: Sequence[str],
        *,
        step_seconds: int = 30,
        deadline: timedelta = timedelta(seconds=30),
        floor_policy: ScaleFloorPolicy | None = None,
    ) -> None:
        selectors = tuple(query.strip() for query in queries if query.strip())
        if not selectors:
            raise ValueError("at least one PromQL selector is required")
        if step_seconds < 1:
            raise ValueError("step_seconds must be strictly positive")
        if deadline.total_seconds() <= 0.0:
            raise ValueError("deadline must be strictly positive")
        self._client = client
        self._queries = selectors
        self._step_seconds = step_seconds
        self._deadline = deadline
        self._floor_policy = floor_policy if floor_policy is not None else ScaleFloorPolicy()

    async def load(
        self, tenant: TenantId, incident: IncidentId, run: RunId, window: IncidentWindow
    ) -> tuple[SignalBaselineInput, ...]:
        # ``tenant``/``incident``/``run`` do not select data here; see the class docstring.
        try:
            return await asyncio.to_thread(self._load_blocking, window)
        except (PrometheusError, DomainError):
            raise TelemetryUnavailableError from None

    def _load_blocking(self, window: IncidentWindow) -> tuple[SignalBaselineInput, ...]:
        """Query every selector and map the result. Blocking; runs off the event loop."""
        collected: list[PrometheusSeries] = []
        for query in self._queries:
            collected.extend(
                self._client.query_range(
                    query,
                    start=window.start,
                    end=window.end,
                    step_seconds=self._step_seconds,
                    deadline=self._deadline,
                )
            )
        # Mapped once across all selectors, so two overlapping selectors that return the same
        # series fail closed instead of yielding a duplicate signal key to the baseline.
        return to_baseline_inputs(series_to_signals(collected), floor_policy=self._floor_policy)
