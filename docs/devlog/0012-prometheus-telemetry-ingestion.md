# Devlog 0012 — Prometheus telemetry ingestion (slices 1–3)

Status: implemented on branch `feat/prometheus-telemetry` (ADR 0017, still `proposed`). Slice 1
landed at `4304dcf`; slices 2 and 3 are the commits this entry accompanies. Slice 4 (bundled demo
profile + first live run) is **not** done.

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

- **A Prometheus client dependency** (`prometheus-api-client` or similar) — rejected. It buys
  little over a dozen lines of `urllib`, and a runtime dependency here costs the stdlib-only
  identity and would need its own dependency ADR.
- **Per-incident PromQL and window stored in PostgreSQL** — deferred. More realistic, but it needs
  a schema migration and API changes; that is product scope, not the minimal credible slice.
- **Push / remote-write ingestion, or a durable tenant-owned ledger** — rejected for v1: stateful
  and much larger, and not required to close the "reads real telemetry" gap.
- **Sorting or de-duplicating malformed sample ordering** — rejected. Silent repair would forge a
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
it means every tenant a process authenticates sees the same metrics — a real multi-tenancy gap,
now documented in the README rather than left in the source only.

## 5. Smallest implemented slice

- **Slice 1 (`4304dcf`)** — `runtime/prometheus.py`: `PrometheusClient` over an injected
  `fetch` callable, `PrometheusLimits` (max response bytes, series, points per series),
  `PrometheusError` as the single message-free failure, and an `over_http` factory whose
  `urllib` read stops one byte past the size limit so an over-large body is never fully buffered.
- **Slice 2** — `series_to_signals`: non-finite samples are dropped as gaps rather than coerced to
  zero (ADR 0010), a series left with no finite point is dropped whole, and three cases fail
  closed as `PrometheusError`: an unnameable series, non-monotonic samples, and two series
  rendering one signal key (which `rank_metric_shifts` would reject as `DuplicateSignalError`).
- **Slice 3** — `PrometheusTelemetrySource`: constructor validation, all selectors mapped in a
  single `series_to_signals` call so cross-selector duplicates also fail closed,
  `asyncio.to_thread` for the blocking work, and `PrometheusError`/`DomainError` mapped to
  `TelemetryUnavailableError`, which the worker already treats as terminal and leakage-safe.
  Config adds `IEC_TELEMETRY=prometheus` plus `IEC_PROM_URL`, `IEC_PROM_QUERIES`,
  `IEC_PROM_STEP_SECONDS`, `IEC_PROM_TIMEOUT_SECONDS`, and `IEC_PROM_BEARER_TOKEN`.

## 6. Experiment or failure scenario

`IEC_PROM_QUERIES` was initially going to reuse the comma separator from `IEC_TOKENS`. That is
wrong: PromQL label lists already contain commas, so
`rate(http_requests_total{code="500",job="api"}[5m])` would have been split mid-selector into two
invalid queries. The separator is a semicolon, which has no meaning in PromQL grammar, and a test
asserts a comma-bearing selector survives parsing intact.

The blocking-I/O risk was made falsifiable rather than argued: a fetch double records
`threading.get_ident()`, and the test asserts it differs from the event loop's thread.

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

Results: **332 tests, OK, 10 skipped** (PostgreSQL and live-Gemini integration tests);
`ruff check` clean; `ruff format` clean; strict `mypy` clean over 89 source files;
`project validation passed (full)`; `git diff --check` clean. `pyproject.toml` and `uv.lock` are
byte-identical to `main` — no new runtime dependency, as ADR 0017 requires.

## 8. What failed or changed

`_parse_idle_sleep` was a single-purpose positive-float parser; two more numeric knobs would have
duplicated it, so it became `_parse_positive_float`/`_parse_positive_int` with byte-identical
error messages.

The Prometheus config tests were first written into `tests/test_runtime.py`, which put the port
change and the adapter in one file and made a clean per-slice commit split impossible. They moved
to `tests/test_prometheus.py`, so the whole Prometheus surface — client, mapper, source, and its
config contract — is tested in one module.

## 9. Limitations

- **Never run against a live Prometheus.** Every test drives canned API bodies through an injected
  `fetch`; nothing here has opened a socket. The README says so explicitly.
- **No bundled demo profile yet.** Slice 4 (a throwaway Prometheus plus a synthetic exporter in
  `docker-compose`) is not written, so the live path is not yet reproducible by a reader.
- **Selectors are process-wide, not per tenant**, so one process serves one Prometheus and all its
  tenants see the same metrics.
- **The deadline is per query, not per `load`.** A configuration with many selectors can spend
  `N × timeout` in the telemetry stage.
- **`runtime/prometheus.py` imports `evaluation.harness.baseline_inputs`** for the scale-floor
  policy. ADR 0017 item 5 sanctions it so baseline behavior stays identical across sources, but
  evaluation code in the production path is a layering smell owed its own refactor.
- **ADR 0017 is still `proposed`.**

## 10. Next question

Does the path actually work against a real Prometheus? Slice 4 answers it: bundle a throwaway
Prometheus plus a synthetic exporter that injects an anomaly, run one investigation end to end,
and record what broke. Only after that does the README's ingestion claim get to lose its caveat.
