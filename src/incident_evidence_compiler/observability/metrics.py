"""A minimal, correct Prometheus text-exposition metrics registry (stdlib only)."""

import threading
import time
from collections.abc import Sequence
from types import TracebackType

# Cumulative-bucket upper bounds (seconds) for stage-latency histograms.
DEFAULT_LATENCY_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
)

_METRIC_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_:")
_LabelKey = tuple[str, ...]


def _validate_name(name: str) -> str:
    if (
        not name
        or name[0].isdigit()
        or any(character not in _METRIC_NAME_CHARS for character in name)
    ):
        raise ValueError(f"invalid metric name: {name!r}")
    return name


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _render_labels(labelnames: Sequence[str], values: _LabelKey, extra: str | None = None) -> str:
    pairs = [
        f'{name}="{_escape_label_value(value)}"'
        for name, value in zip(labelnames, values, strict=True)
    ]
    if extra is not None:
        pairs.append(extra)
    return "{" + ",".join(pairs) + "}" if pairs else ""


def _check_labels(labelnames: tuple[str, ...], labels: Sequence[str]) -> _LabelKey:
    key = tuple(labels)
    if len(key) != len(labelnames):
        raise ValueError(f"expected {len(labelnames)} label values, got {len(key)}")
    return key


class Counter:
    """A monotonically increasing counter, optionally partitioned by labels."""

    def __init__(self, name: str, documentation: str, labelnames: Sequence[str] = ()) -> None:
        self.name = _validate_name(name)
        self.documentation = documentation
        self.labelnames = tuple(labelnames)
        self._values: dict[_LabelKey, float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, *, labels: Sequence[str] = ()) -> None:
        if amount < 0:
            raise ValueError("counters cannot decrease")
        key = _check_labels(self.labelnames, labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def _render_lines(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.documentation}", f"# TYPE {self.name} counter"]
        with self._lock:
            items = sorted(self._values.items())
        if not items and not self.labelnames:
            items = [((), 0.0)]
        for key, value in items:
            lines.append(f"{self.name}{_render_labels(self.labelnames, key)} {_format(value)}")
        return lines


class Histogram:
    """A cumulative histogram with fixed buckets, optionally partitioned by labels."""

    def __init__(
        self,
        name: str,
        documentation: str,
        buckets: Sequence[float] = DEFAULT_LATENCY_BUCKETS,
        labelnames: Sequence[str] = (),
    ) -> None:
        self.name = _validate_name(name)
        self.documentation = documentation
        self.labelnames = tuple(labelnames)
        self._bounds = tuple(sorted(float(bound) for bound in buckets))
        if not self._bounds:
            raise ValueError("a histogram needs at least one bucket")
        # per label-set: (per-bucket counts aligned to _bounds, sum, count)
        self._counts: dict[_LabelKey, list[int]] = {}
        self._sums: dict[_LabelKey, float] = {}
        self._totals: dict[_LabelKey, int] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, *, labels: Sequence[str] = ()) -> None:
        key = _check_labels(self.labelnames, labels)
        with self._lock:
            counts = self._counts.setdefault(key, [0] * len(self._bounds))
            for index, bound in enumerate(self._bounds):
                if value <= bound:
                    counts[index] += 1
            self._sums[key] = self._sums.get(key, 0.0) + value
            self._totals[key] = self._totals.get(key, 0) + 1

    def time(self, *, labels: Sequence[str] = ()) -> "_Timer":
        return _Timer(self, tuple(labels))

    def _render_lines(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.documentation}", f"# TYPE {self.name} histogram"]
        with self._lock:
            keys = sorted(self._counts)
            snapshot = {
                key: (list(self._counts[key]), self._sums[key], self._totals[key]) for key in keys
            }
        for key in keys:
            counts, total_sum, total = snapshot[key]
            # ``counts[i]`` already holds the number of observations <= bound[i]
            # (accumulated in ``observe``), which is exactly the cumulative bucket value.
            for bound, count in zip(self._bounds, counts, strict=True):
                le = _format(bound)
                labels = _render_labels(self.labelnames, key, extra=f'le="{le}"')
                lines.append(f"{self.name}_bucket{labels} {count}")
            inf_labels = _render_labels(self.labelnames, key, extra='le="+Inf"')
            lines.append(f"{self.name}_bucket{inf_labels} {total}")
            base = _render_labels(self.labelnames, key)
            lines.append(f"{self.name}_sum{base} {_format(total_sum)}")
            lines.append(f"{self.name}_count{base} {total}")
        return lines


class _Timer:
    """Context manager that observes elapsed monotonic seconds into a histogram."""

    def __init__(self, histogram: Histogram, labels: _LabelKey) -> None:
        self._histogram = histogram
        self._labels = labels
        self._start = 0.0

    def __enter__(self) -> "_Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._histogram.observe(time.perf_counter() - self._start, labels=self._labels)


def _format(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return repr(value)


class MetricsRegistry:
    """A thread-safe registry of counters and histograms with idempotent registration."""

    def __init__(self) -> None:
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}
        self._lock = threading.Lock()

    def counter(self, name: str, documentation: str, labelnames: Sequence[str] = ()) -> Counter:
        with self._lock:
            existing = self._counters.get(name)
            if existing is not None:
                return existing
            counter = Counter(name, documentation, labelnames)
            self._counters[name] = counter
            return counter

    def histogram(
        self,
        name: str,
        documentation: str,
        buckets: Sequence[float] = DEFAULT_LATENCY_BUCKETS,
        labelnames: Sequence[str] = (),
    ) -> Histogram:
        with self._lock:
            existing = self._histograms.get(name)
            if existing is not None:
                return existing
            histogram = Histogram(name, documentation, buckets, labelnames)
            self._histograms[name] = histogram
            return histogram

    def render(self) -> str:
        with self._lock:
            metrics: list[Counter | Histogram] = [
                *self._counters.values(),
                *self._histograms.values(),
            ]
        metrics.sort(key=lambda metric: metric.name)
        lines: list[str] = []
        for metric in metrics:
            lines.extend(metric._render_lines())
        return "\n".join(lines) + "\n" if lines else ""
