"""Run one whole investigation against the real server, with nothing but Python installed.

    uv run --locked python scripts/demo_hermetic_investigation.py

No Docker, no Prometheus, no database, no cloud project, no network egress. The script picks a
free loopback port, starts ``python -m incident_evidence_compiler`` as a subprocess exactly the
way the container does, waits for ``GET /health``, then submits one investigation over HTTP and
polls for the verified report. It never imports a use case and calls it: everything crosses the
real API boundary, so a break in the entrypoint, the config parsing, the auth dependency, the
worker loop or the report endpoint shows up here.

What is not real is stated on the first line of the output rather than buried: the hypothesis
comes from the labelled smoke client (no model call), the store is in memory, and the telemetry
is the small synthetic fixture committed under ``tests/fixtures`` rather than a live cluster.
The evidence ledger, the content-addressed evidence ids, the verifier and the deterministic
baseline ranking are the same code that runs against real telemetry.

Standard library plus the project package only.
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# The script directory is not on sys.path under PYTHONSAFEPATH=1, ``python -P`` or ``python -I``.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _demo_common import format_baseline_ranking, format_predicates

from incident_evidence_compiler.domain.identifiers import IncidentId, RunId, TenantId
from incident_evidence_compiler.runtime import RcaevalTelemetrySource

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "rcaeval" / "RE2-OB"
SPLIT = "OB"
TOKEN = "demo-token"
TENANT = "tenant-demo"
BANNER = (
    "no model: labelled smoke client; no database: in-memory store; no network: loopback only;"
    " telemetry: committed synthetic fixture;"
    " the API, worker, evidence ledger and verifier are the real ones"
)
# Wall-clock budgets, not attempt counts, so the whole run is bounded (about 75 s worst case
# including shutdown) and always finishes before the end-to-end test's timeout kills it. If the
# test killed the driver first, the driver's cleanup would never run and the server it started
# would be orphaned on its port.
HEALTH_DEADLINE_SECONDS = 15.0
REPORT_DEADLINE_SECONDS = 30.0
POLL_SECONDS = 0.5
LOG_TAIL_LINES = 20
# Anything the operator exported for their own IEC deployment must not leak into the demo: an
# ambient IEC_WORKER_ENABLED=false or IEC_BASELINE_MIN_SCORE would silently change what a reader
# sees. Only the variables set below reach the child.
_STRIPPED_PREFIXES = ("IEC_",)
_STRIPPED_KEYS = frozenset({"GEMINI_API_KEY"})


class DemoError(Exception):
    """A demo step that did not complete, with a short reason a reader can act on."""


def _free_port() -> int:
    """Ask the operating system for an unused loopback port and hand it straight back."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _server_environment(port: int) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(_STRIPPED_PREFIXES) and key not in _STRIPPED_KEYS
    }
    environment.update(
        {
            "IEC_TOKENS": f"{TOKEN}={TENANT}",
            "IEC_PERSISTENCE": "memory",
            "IEC_LLM_PROVIDER": "fake",
            "IEC_TELEMETRY": "rcaeval",
            "IEC_RE2_ROOT": str(FIXTURE_ROOT),
            "IEC_RE2_SPLIT": SPLIT,
            "IEC_BIND_HOST": "127.0.0.1",
            "IEC_BIND_PORT": str(port),
        }
    )
    return environment


def _get(url: str, *, timeout: float, token: str | None = None) -> bytes:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body: bytes = response.read()
        return body


async def _signal_count(source: RcaevalTelemetrySource, incident: str, window: Any) -> int:
    inputs = await source.load(TenantId(TENANT), IncidentId(incident), RunId("run-1"), window)
    return len(inputs)


def _pick_case() -> tuple[str, dict[str, str]]:
    """Index the committed fixture and choose the case with the most signals, deterministically.

    More signals means the baseline has something to rank, so the printed ranking shows a lead
    over a runner-up rather than a single line. Ties break on the opaque id.

    The ids are opaque ``case-<digest>`` values on purpose: a RE2 directory is named
    ``<service>_<fault>``, and the incident id is embedded verbatim in the prompt, so serving the
    directory name would hand the model the answer. The locator is never printed here.
    """
    try:
        source = RcaevalTelemetrySource(FIXTURE_ROOT, split=SPLIT)
        available = source.available
        counts = {
            incident: asyncio.run(_signal_count(source, incident, window))
            for incident, window in available.items()
        }
    except Exception as error:
        raise DemoError(
            f"the committed RE2-OB fixture could not be indexed ({type(error).__name__})"
        ) from error
    if not available:
        raise DemoError("the committed RE2-OB fixture indexed no parseable case")
    incident = max(sorted(available), key=lambda case: counts[case])
    window = available[incident]
    return incident, {
        "start": window.start.isoformat(),
        "injection": window.injection.isoformat(),
        "end": window.end.isoformat(),
    }


def _wait_for_health(base_url: str, process: "subprocess.Popen[str]") -> None:
    deadline = time.monotonic() + HEALTH_DEADLINE_SECONDS
    while True:
        if process.poll() is not None:
            raise DemoError(f"the control plane exited early with code {process.returncode}")
        try:
            _get(f"{base_url}/health", timeout=3.0)
        except (urllib.error.URLError, OSError, TimeoutError):
            if time.monotonic() >= deadline:
                raise DemoError("the control plane never answered /health") from None
            time.sleep(POLL_SECONDS)
        else:
            return


def _error_code(error: urllib.error.HTTPError) -> str:
    """The stable ``code`` field of an error body, or ``unknown``; never the raw body."""
    try:
        body = json.loads(error.read().decode("utf-8", errors="replace"))
        code = body.get("code") if isinstance(body, dict) else None
        return code if isinstance(code, str) and code.isidentifier() else "unknown"
    except (OSError, ValueError, AttributeError):
        return "unknown"


def _post_investigation(base_url: str, incident: str, window: dict[str, str]) -> str:
    payload = json.dumps({"incident_id": incident, "run_id": "run-1", "window": window}).encode()
    request = urllib.request.Request(
        f"{base_url}/investigations",
        data=payload,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Idempotency-Key": f"demo-{incident}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10.0) as response:
            if response.status != 202:
                raise DemoError(f"POST /investigations answered {response.status}, expected 202")
            accepted = json.loads(response.read())
            investigation_id = accepted["investigation_id"]
    except urllib.error.HTTPError as error:
        raise DemoError(
            f"POST /investigations answered {error.code} ({_error_code(error)})"
        ) from None
    except (urllib.error.URLError, OSError, TimeoutError, ValueError, KeyError, TypeError) as error:
        raise DemoError(f"POST /investigations failed ({type(error).__name__})") from None
    if not isinstance(investigation_id, str):
        raise DemoError("POST /investigations answered 202 without an investigation id")
    return investigation_id


def _poll_report(
    base_url: str, investigation_id: str, process: "subprocess.Popen[str]"
) -> dict[str, Any]:
    url = f"{base_url}/investigations/{investigation_id}/report"
    deadline = time.monotonic() + REPORT_DEADLINE_SECONDS
    last = "no attempt completed"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise DemoError(f"the control plane exited early with code {process.returncode}")
        try:
            report: dict[str, Any] = json.loads(_get(url, timeout=5.0, token=TOKEN))
            return report
        except urllib.error.HTTPError as error:
            # 409 report_not_ready is the one answer worth waiting on; every other status is a
            # definite failure and is reported at once rather than retried into a timeout.
            if error.code != 409:
                raise DemoError(
                    f"GET report answered {error.code} ({_error_code(error)})"
                ) from None
            last = "HTTP 409"
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as error:
            last = type(error).__name__
        time.sleep(POLL_SECONDS)
    raise DemoError(f"the report never became ready (last answer: {last})")


def _terminate(process: "subprocess.Popen[str]") -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10.0)


def _drain(stream: Iterable[str], sink: "deque[str]") -> None:
    """Keep the child's pipe empty so it can never block on a full buffer.

    Only the last few lines are kept: on success nothing is printed, and on failure a short tail
    is more useful to a reader than a screen of uvicorn access logs.
    """
    for line in stream:
        sink.append(line.rstrip("\r\n"))


def _print_log_tail(tail: "deque[str]") -> None:
    if not tail:
        return
    plural = "line" if len(tail) == 1 else "lines"
    print(f"last {len(tail)} {plural} of the control plane log:", file=sys.stderr)
    for line in tail:
        print(f"  {line}", file=sys.stderr)


def _investigate(
    base_url: str,
    process: "subprocess.Popen[str]",
    incident: str,
    window: dict[str, str],
) -> None:
    _wait_for_health(base_url, process)
    print(f"control plane ready at {base_url}/health")
    investigation_id = _post_investigation(base_url, incident, window)
    print(f"investigation {investigation_id} accepted; polling for the report")
    report = _poll_report(base_url, investigation_id, process)

    body = report.get("report")
    verdict = body.get("verdict", "?") if isinstance(body, dict) else "?"
    predicates = format_predicates(report)
    print()
    print(f"verdict: {verdict}")
    if predicates:
        print(predicates)
    print()
    print(format_baseline_ranking(report))


def main() -> int:
    print(BANNER)
    try:
        incident, window = _pick_case()
    except DemoError as error:
        print(f"demo failed: {error}", file=sys.stderr)
        return 1
    print(f"incident {incident} (opaque case id), window {window['start']} .. {window['end']}")

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    print(f"starting python -m incident_evidence_compiler on {base_url}")

    failure: str | None = None
    interrupted = False
    tail: deque[str] = deque(maxlen=LOG_TAIL_LINES)
    process = subprocess.Popen(
        [sys.executable, "-m", "incident_evidence_compiler"],
        cwd=ROOT,
        env=_server_environment(port),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None
    reader = threading.Thread(target=_drain, args=(process.stdout, tail), daemon=True)
    reader.start()
    try:
        _investigate(base_url, process, incident, window)
    except DemoError as error:
        failure = str(error)
    except BaseException:
        # A KeyboardInterrupt or an unexpected error still gets the server stopped (below) and
        # the log tail printed, so an interrupted run leaves neither an orphan nor a mystery.
        interrupted = True
        raise
    finally:
        # Terminating closes the write end of the pipe, so the reader sees EOF and stops on its
        # own; the stream is only closed once nothing is iterating it.
        _terminate(process)
        reader.join(timeout=5.0)
        process.stdout.close()
        if interrupted:
            _print_log_tail(tail)

    if failure is not None:
        print(f"demo failed: {failure}", file=sys.stderr)
        _print_log_tail(tail)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
