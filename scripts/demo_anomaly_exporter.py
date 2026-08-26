"""A synthetic payment-infrastructure incident exporter for the ingestion demo (ADR 0018).

This file invents numbers. It is not production telemetry, not a benchmark, and not evidence of
anything about real payment systems. Its only job is to give a bundled throwaway Prometheus
something real to scrape, so the real ingestion path (`IEC_TELEMETRY=prometheus`) can be exercised
end to end against a real server. Standard-library only, one route, no dependency.

The scenario is a payment-routing incident. Four components are exposed, ``bank_router``,
``checkout``, ``upi_switch``, and ``ledger_db``. Before the injection instant every component looks
alike. After it, modelling a ``bank_router`` deploy gone bad, ``bank_router`` degrades: its
latency climbs by roughly an order of magnitude and its error ratio jumps, while the others stay
flat. ``ledger_db`` is a deliberate healthy decoy: a database-shaped signal a model might wrongly
blame, so the verifier's ``unknown`` refusal can be shown against real ingested data. The faulty
component is the shift the deterministic baseline is expected to rank first.

The exporter publishes ``demo_injection_unixtime`` so a client can build an incident window that
straddles the injection exactly, instead of guessing.

Usage:
    DEMO_INJECT_AFTER_SECONDS=60 python scripts/demo_anomaly_exporter.py
    # serves 0.0.0.0:9101/metrics
"""

import math
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_COMPONENTS = ("bank_router", "checkout", "ledger_db", "upi_switch")
_FAULTY = "bank_router"

_BASELINE_LATENCY_SECONDS = 0.10
_DEGRADED_LATENCY_SECONDS = 0.95
_BASELINE_ERROR_RATIO = 0.002
_DEGRADED_ERROR_RATIO = 0.180

_STARTED_AT = time.time()
_INJECT_AFTER_SECONDS = float(os.environ.get("DEMO_INJECT_AFTER_SECONDS", "60"))
_INJECTION_UNIXTIME = _STARTED_AT + _INJECT_AFTER_SECONDS
_PORT = int(os.environ.get("DEMO_EXPORTER_PORT", "9101"))


def _wobble(component: str, now: float) -> float:
    """A small deterministic per-component oscillation, so no signal is perfectly constant.

    A perfectly flat signal has zero robust spread, which makes any shift look infinitely
    significant. A little motion keeps the baseline's arithmetic honest.
    """
    phase = float(sum(ord(character) for character in component))
    return 1.0 + 0.04 * math.sin(now / 7.0 + phase)


def _sample(component: str, now: float) -> tuple[float, float]:
    """Return ``(latency_seconds, error_ratio)`` for one component at ``now``."""
    degraded = component == _FAULTY and now >= _INJECTION_UNIXTIME
    latency = _DEGRADED_LATENCY_SECONDS if degraded else _BASELINE_LATENCY_SECONDS
    errors = _DEGRADED_ERROR_RATIO if degraded else _BASELINE_ERROR_RATIO
    factor = _wobble(component, now)
    return latency * factor, errors * factor


def _render(now: float) -> bytes:
    """Render the Prometheus text exposition format for one scrape."""
    lines = [
        "# HELP payment_latency_seconds Synthetic per-component request latency (DEMO DATA).",
        "# TYPE payment_latency_seconds gauge",
    ]
    latencies: list[str] = []
    ratios: list[str] = []
    for component in _COMPONENTS:
        latency, errors = _sample(component, now)
        latencies.append(f'payment_latency_seconds{{component="{component}"}} {latency:.6f}')
        ratios.append(f'payment_error_ratio{{component="{component}"}} {errors:.6f}')
    lines.extend(latencies)
    lines.extend(
        [
            "# HELP payment_error_ratio Synthetic per-component error ratio (DEMO DATA).",
            "# TYPE payment_error_ratio gauge",
            *ratios,
            "# HELP demo_injection_unixtime Wall-clock instant the synthetic fault begins.",
            "# TYPE demo_injection_unixtime gauge",
            f"demo_injection_unixtime {_INJECTION_UNIXTIME:.3f}",
            "# HELP demo_injected Whether the synthetic fault is currently active.",
            "# TYPE demo_injected gauge",
            f"demo_injected {1 if now >= _INJECTION_UNIXTIME else 0}",
        ]
    )
    return ("\n".join(lines) + "\n").encode()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] != "/metrics":
            self.send_error(404)
            return
        body = _render(time.time())
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return  # a scrape every few seconds would otherwise flood the compose logs


def main() -> int:
    # Binds all interfaces because it only ever runs inside the demo container network.
    server = ThreadingHTTPServer(("0.0.0.0", _PORT), _Handler)
    print(
        f"synthetic payment-incident exporter on :{_PORT}/metrics, DEMO DATA; "
        f"'{_FAULTY}' degrades at unixtime {_INJECTION_UNIXTIME:.0f} "
        f"(+{_INJECT_AFTER_SECONDS:.0f}s)",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
