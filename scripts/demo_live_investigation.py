"""Drive one live investigation against the bundled demo stack (ADR 0017).

This is the script that makes the first genuine ingestion run reproducible. It reads the
synthetic exporter's published injection instant so the incident window straddles the fault
exactly rather than by guesswork, waits for the window to fill with real scrapes, then submits
an investigation and polls for the verified report.

The telemetry is invented (see ``demo_anomaly_exporter.py``); the Prometheus, the range query,
the worker, and the verifier are all real. Standard library only, plus the report formatters in
``_demo_common.py`` that this driver shares with the hermetic one so both print alike.

Usage (after `docker compose --profile demo up -d --build`):
    uv run --locked python scripts/demo_live_investigation.py
"""

import argparse
import json
import time
import urllib.error
import urllib.request
from typing import Any

from _demo_common import format_baseline_ranking, format_predicates

_DEFAULT_EXPORTER = "http://127.0.0.1:9101/metrics"
_DEFAULT_COMPILER = "http://127.0.0.1:8000"
_DEFAULT_TOKEN = "demo-token"


def _get(url: str, timeout: float, token: str | None = None) -> bytes:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body: bytes = response.read()
        return body


def _wait_for(url: str, label: str, attempts: int, token: str | None = None) -> None:
    for remaining in range(attempts, 0, -1):
        try:
            _get(url, timeout=3.0, token=token)
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            if remaining == 1:
                raise SystemExit(f"{label} never became ready at {url}: {error}") from None
            time.sleep(1.0)
        else:
            print(f"  {label} ready at {url}")
            return


def _injection_unixtime(exporter_url: str) -> float:
    """Read the exporter's published injection instant from its own /metrics output."""
    for line in _get(exporter_url, timeout=5.0).decode().splitlines():
        if line.startswith("demo_injection_unixtime "):
            return float(line.split(" ", 1)[1])
    raise SystemExit("exporter did not publish demo_injection_unixtime")


def _iso(unixtime: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(unixtime))


def _post_investigation(base_url: str, token: str, window: dict[str, str], incident: str) -> str:
    payload = json.dumps({"incident_id": incident, "run_id": "run-1", "window": window}).encode()
    request = urllib.request.Request(
        f"{base_url}/investigations",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Idempotency-Key": incident,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10.0) as response:
        if response.status != 202:
            raise SystemExit(f"expected 202 Accepted, got {response.status}")
        accepted: dict[str, Any] = json.loads(response.read())
    return str(accepted["investigation_id"])


def _poll_report(base_url: str, token: str, investigation_id: str, attempts: int) -> dict[str, Any]:
    url = f"{base_url}/investigations/{investigation_id}/report"
    last = ""
    for _ in range(attempts):
        try:
            report: dict[str, Any] = json.loads(_get(url, timeout=5.0, token=token))
            return report
        except urllib.error.HTTPError as error:
            # 409 report_not_ready is expected until the worker finishes the pipeline.
            last = f"HTTP {error.code} {error.read().decode(errors='replace')[:200]}"
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            last = str(error)
        time.sleep(1.0)
    status = _get(f"{base_url}/investigations/{investigation_id}", timeout=5.0, token=token)
    raise SystemExit(f"report never became ready: {last}\nlast status: {status.decode()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exporter-url", default=_DEFAULT_EXPORTER)
    parser.add_argument("--compiler-url", default=_DEFAULT_COMPILER)
    parser.add_argument("--token", default=_DEFAULT_TOKEN)
    parser.add_argument(
        "--half-window-seconds",
        type=int,
        default=120,
        help="Seconds of telemetry on each side of the injection instant.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args()

    print("waiting for the demo stack")
    _wait_for(args.exporter_url, "exporter", attempts=30)
    _wait_for(f"{args.compiler_url}/health", "compiler", attempts=60)

    injection = _injection_unixtime(args.exporter_url)
    start = injection - args.half_window_seconds
    end = injection + args.half_window_seconds
    print(f"injection at {_iso(injection)}; window {_iso(start)} .. {_iso(end)}")

    remaining = end - time.time()
    if remaining > 0:
        print(f"waiting {remaining:.0f}s for Prometheus to scrape the whole window")
        time.sleep(remaining + 2.0)

    incident = f"payments-{int(injection)}"
    window = {"start": _iso(start), "injection": _iso(injection), "end": _iso(end)}
    investigation_id = _post_investigation(args.compiler_url, args.token, window, incident)
    print(f"investigation {investigation_id} accepted; polling for the report")

    report = _poll_report(
        args.compiler_url, args.token, investigation_id, attempts=args.timeout_seconds
    )
    verdict = report["report"]["verdict"]
    predicates = format_predicates(report)
    print(f"\nverdict: {verdict}")
    if predicates:
        print(predicates)
    print()
    print(format_baseline_ranking(report))
    print(json.dumps(report, indent=2)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
