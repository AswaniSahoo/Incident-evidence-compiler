"""Dependency-free Prometheus-style metrics.

A small, thread-safe in-process registry of counters and histograms that renders the
Prometheus text exposition format. Kept standard-library only (no ``prometheus-client``) to
match the project's minimal-dependency stance; the metric set is bounded and carries no
tenant or PII labels, so the ``/metrics`` surface is safe to expose to a scraper.
"""

from .metrics import (
    DEFAULT_LATENCY_BUCKETS,
    Counter,
    Histogram,
    MetricsRegistry,
)

__all__ = [
    "DEFAULT_LATENCY_BUCKETS",
    "Counter",
    "Histogram",
    "MetricsRegistry",
]
