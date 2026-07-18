# 0016 — Runnable server entrypoint and container image (Phase 9)

- Status: accepted
- Date: 2026-07-18
- Deciders: Aswani
- Supersedes: none
- Related: 0007 (two-week sprint / cut order), 0011 (persistence boundary), 0012 (LLM provider
  boundary), 0013 (control plane + worker), 0014 (real-data evaluation), 0015 (observability)

## Context

Phases 0–8 delivered a verified deterministic domain, PostgreSQL persistence with a
`SKIP LOCKED` worker queue, an async Gemini provider boundary, a FastAPI control plane, a
real-data evaluation, and a dependency-free `/metrics` endpoint. Everything was exercised
**in-process** — the control plane through `httpx.ASGITransport`, the worker by directly
calling `run_once`. There was no committed way to actually *run* the system as a process, and
no container image. The v1 ship plan (`MASTER-PLAN.md`, ADR 0007) lists "runnable server
entrypoint + Dockerfile + docker-build CI gate" as the last remaining code slice before the
sealed run and demo.

The blocker was never the HTTP wiring; it was **telemetry**. The worker needs a
`TelemetrySource`, but v1 has no production telemetry-ingestion path — the only real metric
data the project has is RCAEval RE2, and the only in-repo source was the hermetic in-memory
fake. Wiring a server that silently pretends to have production ingestion would violate the
no-fake-production-claims rule (`AGENTS.md`).

## Decision

Add a composition-root `runtime` package and a `python -m incident_evidence_compiler`
entrypoint that wires the existing ports into a single runnable process, plus a multi-stage
container image and a docker-build + smoke gate in CI. No new runtime dependency:
`uvicorn[standard]` was already approved in phase 6 (ADR 0013).

1. **Single-process topology.** One process runs the FastAPI app *and* an in-process worker
   loop as an ASGI lifespan background task. This is honest for the single-node v1 (ADR 0007
   deferred the Redis/multi-node story); horizontal split into a separate worker process is a
   future change that needs no domain change.

2. **Configuration is environment-only and fail-fast.** A pure `AppConfig.from_env(mapping)`
   parses every knob and raises a typed `ConfigError` with a stable, secret-free message on any
   missing/invalid value. Nothing is silently defaulted into a production-shaped lie.

   - `IEC_PERSISTENCE` = `memory` (default) | `postgres`; `postgres` requires
     `IEC_DATABASE_URL`.
   - `IEC_TOKENS` = `token=tenant` pairs (comma-separated), required and non-empty. Tokens are
     never logged (ADR 0007).
   - `IEC_LLM_PROVIDER` = `fake` (default) | `developer` | `vertex`. `developer` requires
     `GEMINI_API_KEY`; `vertex` requires `IEC_GEMINI_PROJECT` (plus optional
     `IEC_GEMINI_LOCATION`, default `us-central1`). Model is `IEC_GEMINI_MODEL`
     (default `gemini-2.5-flash`).
   - `IEC_TELEMETRY` = `none` (default) | `rcaeval`; `rcaeval` requires `IEC_RE2_ROOT`
     (an already-extracted split directory *outside* the repo, per ADR 0009) and optional
     `IEC_RE2_SPLIT` (default `OB`).
   - `IEC_BIND_HOST` (default `127.0.0.1`), `IEC_BIND_PORT` (default `8000`),
     `IEC_WORKER_ENABLED` (default `1`), `IEC_WORKER_IDLE_SLEEP_SECONDS` (default `1.0`).

3. **The `fake` LLM path is a labelled non-model smoke client, not Gemini.** `FirstSignalLLMClient`
   deterministically proposes an `increase` predicate on the lexicographically-first allowed
   signal. It exists so the system can boot and complete the pipeline end-to-end with zero
   credentials (local smoke, container CI). It is not a model and makes no accuracy claim; the
   real arms are `developer`/`vertex`.

4. **The `rcaeval` telemetry source is a labelled demo source, not production ingestion.**
   `RcaevalTelemetrySource` reuses the existing bounded RCAEval primitives (`discover_cases`,
   `parse_case`, `to_baseline_inputs`) to index cases by their directory path and resolve an
   investigation's `incident_id` to that case's signals and window. It reads only the metric
   CSV, the injection time, and the directory path — it never consults the evaluation sidecar
   or any ground-truth label, and it performs no scoring. Raw RCAEval data is still never
   committed (ADR 0009); the source points at an out-of-repo root.

5. **Container image.** A multi-stage `uv` build (builder installs the locked, no-dev
   environment with bytecode compilation and copy link mode; a slim runtime stage carries only
   the virtualenv and `src`), runs as a non-root user, declares a `HEALTHCHECK` against
   `/health` using the stdlib (no `curl` installed), and defaults `IEC_BIND_HOST=0.0.0.0`
   inside the isolated container while the bare-process default stays `127.0.0.1`.

6. **CI gate.** A shell-based `container` job builds the image and smoke-tests it
   (`memory` + `fake` + `none`): it asserts `/health` and `/metrics` respond. It uses the
   preinstalled Docker on the runner and adds no new pinned GitHub Action.

## Consequences

- The system is runnable (`docker run` or `python -m incident_evidence_compiler`) and the image
  is built and smoke-tested on every push. The hermetic gate is unchanged and stays green with
  no database, network, or credentials.
- `/metrics` and `/health` are intentionally open (ADR 0015). Restrict network access to the
  scrape/health surface at deployment; the default bind for a bare process is loopback.
- **Explicit non-goal (documented limitation):** there is still no production telemetry
  ingestion. The `rcaeval` demo source and the `fake` smoke client make this honest rather than
  hidden. A durable, tenant-owned telemetry ledger is future work.
- Phase governance advances to Phase 9: the validator gains the Phase 9 required-file set and a
  scope exception that permits a root `Dockerfile`.

## Alternatives considered

- **Separate `serve` and `worker` entrypoints/processes.** More faithful to a multi-node
  deployment, but v1 is explicitly single-node (ADR 0007) and it complicates the demo (two
  containers). Deferred; the in-process lifespan task is a clean seam to split later.
- **Always require real Gemini credentials to boot.** Rejected: it removes the credential-free
  local/CI smoke path. Real credentials remain the default intent for the operator; `fake` is
  opt-in and clearly non-model.
- **A generic `{tenant}/{incident}/{run}` directory telemetry source.** Cleaner separation from
  the evaluation package, but it would duplicate the already-audited RCAEval parser and offer no
  real telemetry beyond what `rcaeval` already gives. Deferred until a real ingestion format
  exists.
