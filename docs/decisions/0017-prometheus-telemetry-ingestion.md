# 0017 — Production telemetry ingestion via Prometheus

- Status: proposed
- Date: 2026-08-20
- Deciders: Aswani
- Supersedes: none
- Related: 0009 (guardrailed real data), 0010 (missing cells are gaps), 0013 (control plane +
  worker), 0016 (runnable entrypoint — named telemetry ingestion as the explicit v1 non-goal)

## Context

ADR 0016 shipped a runnable, containerized system but recorded that its one honest gap is
**production telemetry ingestion**: the worker consumes a `TelemetrySource`, yet the only real
sources are the hermetic in-memory fake and a labelled RCAEval demo bridge. The system has never
read telemetry from a live monitoring system. This is the top limitation in the README and the
single change that turns "investigates canned benchmark data" into "ingests real telemetry."

Two facts about the existing seam make this a small, contained change:

- The `TelemetrySource` port is narrow: `async load(tenant, incident, run) -> tuple[SignalBaselineInput, ...]`.
  It returns only signals; the **incident window** comes separately from `investigation.window`
  in the worker (`worker.py`, `_run_pipeline`), which is already loaded before the telemetry call.
- The core pipeline (evidence ledger → baseline → verifier) is unchanged by *where* signals come
  from. Adding ingestion means adding one **adapter behind the existing port**, not touching the
  frozen domain.

Prometheus is the most common open-source metrics store; its range-query API is plain HTTP + JSON,
which the Python standard library already covers.

## Decision

Add a read-only `PrometheusTelemetrySource` that range-queries a live Prometheus over the incident
window and maps each returned series to a `MetricSignal`, feeding the existing pipeline unchanged.

1. **Stdlib only — no new dependency.** The client uses `urllib.request` + `json` to call
   Prometheus `GET /api/v1/query_range`. This preserves the project's stdlib-only runtime identity
   (deps only when an ADR sanctions them) and needs no dependency ADR or lockfile change.

2. **Config-provided PromQL selectors (not per-incident storage).** `AppConfig` gains, when
   `IEC_TELEMETRY=prometheus`: `IEC_PROM_URL` (base URL, required), `IEC_PROM_QUERIES` (one or more
   PromQL selectors), `IEC_PROM_STEP_SECONDS` (sample step), `IEC_PROM_TIMEOUT_SECONDS` (deadline),
   and optional `IEC_PROM_BEARER_TOKEN`. All parsed fail-fast via the existing `ConfigError` path;
   the token is never echoed in an error. Per-incident query storage in Postgres is deferred future
   work, not v1.

3. **Port change: pass the incident window.** `TelemetrySource.load` gains a trailing
   `window: IncidentWindow` argument so a live source has a `[start, end]` to query. The two
   existing sources (`InMemoryTelemetrySource`, `RcaevalTelemetrySource`) accept and ignore it
   (their data is pre-indexed); the worker passes `investigation.window`. One small, principled
   interface change with a mechanical ripple to two sources and their tests.

4. **Bounded and fail-closed, like every other external boundary.** The client enforces a socket
   deadline, a maximum response size, a maximum series count, and a maximum points-per-series
   (a `PrometheusLimits` mirroring the RCAEval `LoaderLimits`). Missing/non-finite samples are
   dropped as gaps (never coerced to zero), consistent with ADR 0010. Any timeout, transport error,
   non-2xx status, malformed body, or limit breach raises a typed failure that the source maps to
   `TelemetryUnavailableError` — which the worker already treats as a terminal, leakage-safe
   failure. Untrusted response bodies are validated before any value is trusted.

5. **Series → signal mapping.** Each Prometheus series' metric name + labels render a stable signal
   name; its `(timestamp, value)` samples become `MetricPoint`s; the resulting `MetricSignal`s pass
   through the same `to_baseline_inputs` the demo source uses, so baseline behavior stays identical.

6. **Demo via a bundled throwaway Prometheus (Option ii).** `docker-compose` gains an optional
   profile with a real Prometheus plus a tiny synthetic exporter that emits an injected anomaly, so
   a single command demonstrates a genuine end-to-end ingestion. This is a **real** Prometheus and
   the **real** ingestion path fed **synthetic** data — clearly labelled as demo data, so it makes
   no fake production claim (AGENTS.md). Production scrape/remote-write topologies remain out of
   scope.

## Consequences

- Closes the #1 documented limitation; the README limitation flips to "ingests real telemetry via
  Prometheus (read-only range queries); production scrape topologies still out of scope."
- The port signature change touches `application/telemetry.py`, `runtime/telemetry.py`,
  `runtime/server.py`, `application/worker.py`, and their tests — all mechanical.
- No new runtime dependency; `pyproject.toml`/`uv.lock` unchanged; the phase gate is unchanged.
- New env surface is documented and fail-fast; no secret is logged.
- Built in TDD slices: (1) bounded stdlib client, (2) series→signal mapper, (3) source + port
  change + config wiring, (4) demo compose profile + docs.

## Alternatives considered

- **`prometheus-api-client` (or similar) dependency** — rejected: it buys little over a dozen lines
  of `urllib`, and adding a runtime dependency here *costs* credibility against the stdlib-only
  identity and would require its own dependency ADR.
- **Per-incident PromQL/window stored in Postgres** — deferred: more realistic but needs a schema
  migration and API changes; it is product scope, not the minimal credible ingestion slice.
- **Push / remote-write ingestion or a durable tenant-owned ledger** — rejected for v1: stateful,
  much larger, and not required to close the "reads real telemetry" gap.
