# Devlog 0012, Prometheus telemetry ingestion (slices 1–4)

Status: implemented on branch `feat/prometheus-telemetry` (ADR 0017, **accepted**). Slice 1
landed at `4304dcf`; slices 2 and 3 followed. Slice 4, the bundled demo profile and the live run
against a real Prometheus, is **done**: an ingestion-only run (fake client) on 2026-08-22, and a
run through real **Vertex Gemini** on 2026-08-23. Both are in sections 6 and 7.

## 1. Problem

ADR 0016 shipped a runnable, containerized system and recorded one honest gap: the service had
never read telemetry from a live monitoring system. Its only sources were an in-memory fake and a
labelled RCAEval demo bridge, which made "ingests real telemetry" the top README limitation.

## 2. First principle

Telemetry is untrusted input arriving over a network, so it belongs behind the same treatment as
the LLM boundary: one adapter behind the existing port, bounded in every dimension, and collapsing
every failure into one typed error rather than leaking a response body. The frozen domain must not
move to accommodate a new source.

## 3. Alternatives considered

- **A Prometheus client dependency** (`prometheus-api-client` or similar), rejected. It buys
  little over a dozen lines of `urllib`, and a runtime dependency here costs the stdlib-only
  identity and would need its own dependency ADR.
- **Per-incident PromQL and window stored in PostgreSQL**, deferred. More realistic, but it needs
  a schema migration and API changes; that is product scope, not the minimal credible slice.
- **Push / remote-write ingestion, or a durable tenant-owned ledger**, rejected for v1: stateful
  and much larger, and not required to close the "reads real telemetry" gap.
- **Sorting or de-duplicating malformed sample ordering**, rejected. Silent repair would forge a
  timeline the server never sent. Non-monotonic samples fail closed instead.

## 4. Decision and trade-offs

Ingestion is a read-only range query behind the unchanged `TelemetrySource` port, standard-library
only. Three trade-offs are worth naming.

The port gained a trailing `window: IncidentWindow` so a live source has a range to query. That is
a breaking interface change, paid once, with a mechanical ripple to two existing sources (which
accept and ignore it) and the worker (which passes `investigation.window`).

`load` is `async` but `urllib` is blocking, so the whole query-and-map step runs through
`asyncio.to_thread`. Without that, one slow Prometheus would stall every other task on the
worker's event loop.

Selectors come from process configuration, not per-incident state. That keeps the slice small, but
it means every tenant a process authenticates sees the same metrics, a real multi-tenancy gap,
now documented in the README rather than left in the source only.

## 5. Smallest implemented slice

- **Slice 1 (`4304dcf`)**, `runtime/prometheus.py`: `PrometheusClient` over an injected
  `fetch` callable, `PrometheusLimits` (max response bytes, series, points per series),
  `PrometheusError` as the single message-free failure, and an `over_http` factory whose
  `urllib` read stops one byte past the size limit so an over-large body is never fully buffered.
- **Slice 2**, `series_to_signals`: non-finite samples are dropped as gaps rather than coerced to
  zero (ADR 0010), a series left with no finite point is dropped whole, and three cases fail
  closed as `PrometheusError`: an unnameable series, non-monotonic samples, and two series
  rendering one signal key (which `rank_metric_shifts` would reject as `DuplicateSignalError`).
- **Slice 3**, `PrometheusTelemetrySource`: constructor validation, all selectors mapped in a
  single `series_to_signals` call so cross-selector duplicates also fail closed,
  `asyncio.to_thread` for the blocking work, and `PrometheusError`/`DomainError` mapped to
  `TelemetryUnavailableError`, which the worker already treats as terminal and leakage-safe.
  Config adds `IEC_TELEMETRY=prometheus` plus `IEC_PROM_URL`, `IEC_PROM_QUERIES`,
  `IEC_PROM_STEP_SECONDS`, `IEC_PROM_TIMEOUT_SECONDS`, and `IEC_PROM_BEARER_TOKEN`.

- **Slice 4**, the bundled demo and the first live run: `scripts/demo_anomaly_exporter.py` (a
  stdlib exporter that holds four services flat and then degrades `checkout` at a published
  `demo_injection_unixtime`), `demo/prometheus.yml` (5s scrape), a `demo` profile in
  `docker-compose.yml` (exporter + real Prometheus + the built image wired to
  `IEC_TELEMETRY=prometheus`), and `scripts/demo_live_investigation.py`, which reads the exporter's
  injection instant so the window straddles the fault exactly rather than by guesswork.

## 6. Experiment or failure scenario

`IEC_PROM_QUERIES` was initially going to reuse the comma separator from `IEC_TOKENS`. That is
wrong: PromQL label lists already contain commas, so
`rate(http_requests_total{code="500",job="api"}[5m])` would have been split mid-selector into two
invalid queries. The separator is a semicolon, which has no meaning in PromQL grammar, and a test
asserts a comma-bearing selector survives parsing intact.

The blocking-I/O risk was made falsifiable rather than argued: a fetch double records
`threading.get_ident()`, and the test asserts it differs from the event loop's thread.

**The live run (2026-08-22).** `docker compose --profile demo up -d --build`, then the driver
script. Prometheus scraped the exporter over a four-minute window straddling the injection; the
worker range-queried it and completed the pipeline. Ingested **8 signals, 35 points each**, and
the baseline returned a `BaselineRanking`:

| Rank | Signal | Score | pre → post |
|---|---|---|---|
| 1 | `demo_error_ratio{service="checkout"}` | 20.19 | 0.0020 → 0.1785 |
| 2 | `demo_request_latency_seconds{service="checkout"}` | 18.24 | 0.1009 → 0.9419 |
| 3–8 | healthy services, both metrics | ≤ 0.29 | unchanged |

The report came back `unknown` / `weak_evidence`. That is correct, not a defect:
`FirstSignalLLMClient` names the lexicographically-first allowed signal, which here is
`demo_error_ratio{...service="cart"}`, a flat signal scoring 0.29 against a
`minimum_score` of 1.0, so the verifier declined the guess. A wrong hypothesis about genuinely
ingested data was refused.

**Failure scenario, also live.** With `docker compose stop prometheus`, a submitted investigation
terminated as `failed` after one attempt (`iec_worker_jobs_total{outcome="failed"} 1`) rather than
retrying, and a log scan for `urllib`, `Traceback`, the upstream address, and connection-refused
text returned nothing: the transport failure collapsed into a stable code with no leakage.

**The live run with a real model (2026-08-23).** Re-run with `IEC_LLM_PROVIDER=vertex` (project
`iec-live-demo`, `gemini-2.5-flash`, `us-central1`) instead of the fake client. Isolation held: the
compiler ran as a host process against the containerized Prometheus so ADC sufficed with no
credential mounted into any image, and another project's ambient `GOOGLE_*`/`GEMINI_API_KEY` were
stripped from the child. The real Vertex call
(`.../projects/iec-live-demo/.../gemini-2.5-flash:generateContent → 200`, 520 prompt + 288
completion tokens) proposed hypothesis `major_service_impact` over three predicates. The verifier
resolved each against the ingested ledger: `checkout_error_increase` and `checkout_latency_increase`
came back **`supported`** (evidence `sha256:b598…`, `sha256:7adb…`); `payment_error_increase` came
back **`unknown`/`weak_evidence`**. Counters: `iec_investigation_verdicts_total{verdict="supported"}
1`, `iec_worker_jobs_total{outcome="succeeded"} 1`, `iec_provider_timeouts_total 0`.

The honest reading matters more than the verdict. Gemini sees only signal *names*, so naming
`checkout` (and `payment`) is a plausible guess toward critical-sounding services, not a data-driven
diagnosis. The injected fault was `checkout`, so the two `supported` predicates are verified true and
the `payment` guess is correctly withheld. The verifier, not the model, is the source of truth:
this run shows it endorsing only what the live telemetry supports and withholding an unverified
guess, the same guarantee the 2026-08-22 fake-client run showed from the refusal side.

## 7. Reproducible evidence

Executed on 2026-08-22 on `feat/prometheus-telemetry`, with `GEMINI_API_KEY` unset so the
opt-in live-Gemini smoke test skips:

```bash
uv run --locked python -m compileall -q src scripts .kiro/hooks tests
uv run --locked python -m unittest discover -s tests -p "test_*.py"
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src tests
uv run --locked python scripts/validate_project.py
git diff --check
```

The live demo, requiring Docker (not part of the hermetic gate):

```bash
docker compose --profile demo up -d --build
uv run --locked python scripts/demo_live_investigation.py
docker compose --profile demo down -v
```

Results: **335 tests, OK, 10 skipped** (PostgreSQL and live-Gemini integration tests);
`ruff check` clean; `ruff format` clean; strict `mypy` clean over 89 source files;
`project validation passed (full)`; `git diff --check` clean. `pyproject.toml` and `uv.lock` are
byte-identical to `main`, no new runtime dependency, as ADR 0017 requires. Docker server 29.5.3,
`prom/prometheus:v3.6.0`.

## 8. What failed or changed

`_parse_idle_sleep` was a single-purpose positive-float parser; two more numeric knobs would have
duplicated it, so it became `_parse_positive_float`/`_parse_positive_int` with byte-identical
error messages.

The Prometheus config tests were first written into `tests/test_runtime.py`, which put the port
change and the adapter in one file and made a clean per-slice commit split impossible. They moved
to `tests/test_prometheus.py`, so the whole Prometheus surface, client, mapper, source, and its
config contract, is tested in one module.

`PrometheusClient.over_http` had been *constructed* in tests but its `urllib` path had never run,
because every other test injects `fetch`. A loopback `http.server` on an ephemeral port now
exercises it for real, URL construction, the bearer header, status handling, and caught nothing
functional but did surface a `mypy` finding: `server_address[0]` is `str | bytes`, so
interpolating it into a URL is unsafe.

The live run exposed a genuine observability gap rather than a bug. The baseline ranked the faulty
service's two signals an order of magnitude above everything else, but the HTTP API exposes only
the verified hypothesis, so that ranking had to be inspected out of band with a throwaway script.
The README now lists this as a limitation and the roadmap as work.

## 9. Limitations

- **Real Prometheus, synthetic numbers.** The demo proves the ingestion path, not diagnostic
  accuracy on production telemetry. The exporter invents its data and says so in its docstring.
- **The demo is not in CI.** It needs Docker and about three minutes, so it stays a manual,
  opt-in run; the hermetic gate is unchanged. `EXPECTED_CI_RUNS_BY_PHASE` in the validator pins
  the gate commands, so adding it would be a deliberate, separate change.
- **Selectors are process-wide, not per tenant**, so one process serves one Prometheus and all its
  tenants see the same metrics.
- **The deadline is per query, not per `load`.** A configuration with many selectors can spend
  `N × timeout` in the telemetry stage.
- **`runtime/prometheus.py` imports `evaluation.harness.baseline_inputs`** for the scale-floor
  policy. ADR 0017 item 5 sanctions it so baseline behavior stays identical across sources, but
  evaluation code in the production path is a layering smell owed its own refactor.
- **ADR 0017 is still `proposed`.**

## 10. Next question

Two, now that ingestion demonstrably works. Should the API expose the baseline's ranking, not just
the verified hypothesis, the live run needed a throwaway script to see the thing the system is
best at? And should the PromQL selectors become per-tenant before v1 ships, or is the process-wide
limitation acceptable for a single-tenant-per-process deployment?
