# Devlog 0010 — Phase 9: runnable entrypoint + container image

Status: implemented on branch `phase/07-real-data` (the last v1 code slice). Finalized with
verified evidence at acceptance.

## Goal

Make the system actually runnable — `python -m incident_evidence_compiler` and `docker run` —
and prove it in CI with a container build + smoke gate, without adding a runtime dependency
(ADR 0016).

## First principle

The blocker was never the HTTP wiring; it was telemetry. v1 has no production telemetry
ingestion, so the entrypoint must be honest about that rather than fake a production-shaped
source. Every startup knob fails fast, and the credential-free paths are explicitly labelled
non-model / demo.

## Smallest implemented slice

- `runtime/config.py`: `AppConfig.from_env(mapping)` — a pure, fail-fast parser that raises a
  stable, secret-free `ConfigError` on any missing/invalid value. Knobs: `IEC_PERSISTENCE`
  (`memory`/`postgres`), `IEC_TOKENS`, `IEC_LLM_PROVIDER` (`fake`/`developer`/`vertex`),
  `IEC_TELEMETRY` (`none`/`rcaeval` + `IEC_RE2_ROOT`), bind host/port, and worker knobs.
- `runtime/demo_llm.py`: `FirstSignalLLMClient` — a labelled non-model smoke client that
  proposes one `increase` predicate on the first allowed signal so the pipeline completes with
  zero credentials. Its output still passes the untrusted-output parser.
- `runtime/telemetry.py`: `RcaevalTelemetrySource` — a labelled demo source that reuses the
  audited RCAEval primitives to index a split by case path and resolve `incident_id` to that
  case's signals/window. It reads only metric CSV + injection time + path; it never touches the
  evaluation sidecar or a ground-truth label, and it scores nothing.
- `runtime/server.py`: `build_components` (composition root), `run_worker_loop` (idle-aware,
  failure-isolating), `create_server_app` (attaches the worker loop to the ASGI lifespan), and
  `main` (env → app → `uvicorn.run`). `__main__.py` exposes `python -m incident_evidence_compiler`.
- `Dockerfile`: multi-stage `uv` build (deps layer, then project), slim non-root runtime,
  stdlib `HEALTHCHECK` against `/health`, `IEC_BIND_HOST=0.0.0.0` inside the isolated container.
- `.github/workflows/ci.yml`: a shell-based `container` job builds the image and smoke-tests a
  running container (`memory` + `fake` + `none`): `/health` and `/metrics` must respond. No new
  pinned GitHub Action.

## Testing strategy

`tests/test_runtime.py` (16 tests, fully hermetic) covers: config parsing (defaults, each
provider/persistence/telemetry mode, and every fail-fast path); the smoke client producing a
parser-accepted hypothesis; the demo telemetry source indexing the committed synthetic fixture
and raising `TelemetryUnavailableError` for an unknown case; and an **end-to-end** run through
the real wiring — a submitted investigation is claimed by the worker and returns a persisted
`supported` report over the CANARY fixture — plus the `run_worker_loop` draining the queue and
stopping cleanly. No network, database, or credentials.

## Verification

Full locked hermetic gate green under Phase 9: `compileall`; unittest (PostgreSQL and
Gemini-live tests skipped); `ruff check`; `ruff format --check`; strict `mypy`;
`python scripts/validate_project.py` (full). The container image builds and passes its
`/health` + `/metrics` smoke test. No new runtime dependency; `pyproject.toml`/`uv.lock`
unchanged. The phase-aware validator now covers Phase 9 and permits a root `Dockerfile`.

## Limitations

There is still no production telemetry ingestion — the `rcaeval` demo source and the `fake`
smoke client make that honest rather than hidden. The worker runs in-process (single-node v1);
splitting it into a separate process is future work. `/health` and `/metrics` are open by
design and must be network-restricted at deployment.

## Next question

A single authorized sealed RE2-TT run for one held-out number (Step 4), then the demo recording
and build-in-public posts (Step 5). That closes the v1 ship plan.
