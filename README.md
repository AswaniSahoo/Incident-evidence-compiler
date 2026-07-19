# Incident Evidence Compiler

[![CI](https://github.com/AswaniSahoo/Incident-evidence-compiler/actions/workflows/ci.yml/badge.svg)](https://github.com/AswaniSahoo/Incident-evidence-compiler/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-304_passing-brightgreen.svg)](tests/)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)
[![Typed](https://img.shields.io/badge/mypy-strict-blue.svg)](pyproject.toml)
[![Domain](https://img.shields.io/badge/domain-stdlib_only-informational.svg)](#principles-the-ones-i-actually-held)
[![License](https://img.shields.io/badge/license-Apache_2.0-blue.svg)](LICENSE)

An incident-investigation service where a language model is allowed to *guess*, but only
deterministic code is allowed to *decide*.

It takes microservice telemetry, compiles it into a content-addressed evidence ledger, and lets
Gemini propose restricted hypotheses over an allow-list of signals. Every hypothesis is then
checked by a deterministic verifier that returns one of three answers: `SUPPORTED`, `REFUTED`,
or `UNKNOWN`. Nothing the model says is trusted until the verifier agrees, and `UNKNOWN` is a
real answer, not a polite way of saying "no."

The whole thing is built the way I'd build a real backend: framework-independent domain,
PostgreSQL as the source of truth, a `SKIP LOCKED` worker queue, every external call on a
deadline, and a test suite that runs with no database, no network, and no credentials.

## Results

Measured on the RCAEval RE2-OB **development** split, 88 cases (2 skipped for a truncated final
row). Metrics are aggregate and label-free; the raw artifacts live in
[`docs/evaluation/`](docs/evaluation/).

| Arm | Top-1 | Top-3 | MRR | Abstention | Invalid evidence IDs |
|---|---|---|---|---|---|
| Baseline (deterministic) | **0.932** | **0.989** | **0.959** | 0.000 | 0 |
| + Gemini (`gemini-2.5-flash`, verified) | 0.080 (0.159 answered) | 0.091 | 0.085 | 0.500 | 0 |

Here's the honest part, because it's the interesting part. The deterministic baseline sees the
actual metric values and localizes the faulty service well. The Gemini arm is handed only the
signal *names* — never the values — so it's guessing among ~72 signals, and it often names a
downstream symptom instead of the cause. It does badly. That's fine. The point of the system is
that the verifier gates those guesses: the model abstained or got filtered half the time, and it
produced **zero** invalid evidence citations. The LLM can be wrong without the system being
wrong.

### Held-out (sealed RE2-TT)

Opened once, on 2026-07-19, against a frozen configuration (commit `c7823cc`) — the same
thresholds and model as the development run, no tuning against TT. 90 cases, 0 skipped. This is
the [sealed-run protocol](docs/evaluation/re2-tt-sealed-protocol.md) executed exactly once;
artifacts: [`re2-tt-baseline.json`](docs/evaluation/re2-tt-baseline.json),
[`re2-tt-gemini.json`](docs/evaluation/re2-tt-gemini.json).

| Arm | Top-1 | Top-3 | MRR | Abstention | Invalid evidence IDs |
|---|---|---|---|---|---|
| Baseline (deterministic) | **0.767** | **0.878** | **0.833** | 0.000 | 0 |
| + Gemini (`gemini-2.5-flash`, verified) | 0.156 (0.368 answered) | 0.156 | 0.156 | 0.578 | 0 |

The held-out numbers hold the same shape as development, on a completely different system
(train-ticket, not the dev split): the deterministic baseline localizes well (Top-1 0.77), and
the verifier-gated Gemini arm stays conservative — it abstained on 52 of 90 cases rather than
assert an unverified cause, and again produced **zero** invalid evidence citations. Accuracy
drops from the dev split (harder, unseen system), which is the honest and expected direction.
Method notes: [ADR 0014](docs/decisions/0014-phase-7-real-data-evaluation.md).

## The question I was trying to answer

Real incidents throw off a mess of metrics, logs, traces, and deploy events that don't always
agree with each other. An LLM is genuinely good at reading that mess and summarizing it. What it
should never be allowed to do is invent a data source, run a query, or assert a cause you can't
check.

So: how do you let a model help with incident triage while keeping every accepted conclusion
tenant-scoped, valid for the time window it claims, replayable byte-for-byte, and tied to
evidence you can point at? This repo is my answer.

## How it works

The domain knows nothing about FastAPI, PostgreSQL, or the Gemini SDK. Everything external sits
behind a port, which is what makes the domain testable in isolation and the infrastructure
swappable.

```mermaid
flowchart TD
    Client["Authenticated client"] -->|"Bearer token"| API["FastAPI control plane<br/>auth + tenant scoping"]
    API -->|"use-cases"| APP["Application core<br/>create / status / report + Worker"]
    APP -->|"UnitOfWork port"| DB[("PostgreSQL<br/>source of truth + job queue")]
    Worker["Async worker loop"] -->|"claim job (FOR UPDATE SKIP LOCKED)"| DB
    Worker -->|"TelemetrySource port"| TEL["Telemetry adapter<br/>(RCAEval RE2, bounded)"]
    Worker -->|"LLMClient port"| LLM["Gemini adapter / FakeLLMClient<br/>(untrusted output)"]
    Worker --> DOM["Domain (stdlib only)<br/>baseline · evidence ledger · verifier"]
    Worker -->|"persist evidence + report"| DB
    Client -->|"GET status / report"| API

    classDef trusted fill:#d5efdd,stroke:#137333,stroke-width:2px,color:#0b3d1a;
    classDef untrusted fill:#fbdcd8,stroke:#c5221f,stroke-width:2px,color:#611a15;
    class DOM,DB trusted;
    class LLM,TEL untrusted;
```

Green is trusted: the deterministic domain and the durable store. Red is untrusted input, model
output and raw telemetry, which has to pass strict validation before anyone believes it.

And here's a single investigation end to end:

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as Control plane
    participant DB as PostgreSQL
    participant W as Worker
    participant D as Domain (trusted)
    participant L as LLM (untrusted)

    C->>API: POST /investigations
    API->>DB: create investigation + enqueue job (idempotent)
    API-->>C: 202 Accepted + investigation_id
    W->>DB: claim one job (FOR UPDATE SKIP LOCKED)
    W->>W: load telemetry (TelemetrySource)
    W->>D: rank_metric_shifts -> robust baseline (or abstain)
    W->>D: compile content-addressed evidence ledger
    W->>L: propose hypotheses over the allow-listed signals only
    L-->>W: untrusted JSON
    W->>D: parse (strict, message-free) + verify_hypothesis
    D-->>W: SUPPORTED / REFUTED / UNKNOWN + cited evidence IDs
    W->>DB: persist one evidence row per ledger entry + one report
    C->>API: GET /investigations/{id}/report
    API-->>C: verdicts + evidence IDs (or 409 if not ready)
```

The call out to the model is bounded by a per-attempt deadline. A provider failure is retried
and then gives up; malformed model output is terminal and records only a stable error code,
never the model's text. A stalled model can't wedge the worker.

## What the verifier actually promises

Every predicate resolves to exactly one of three verdicts, and `UNKNOWN` fails closed.

| Verdict | When | Evidence cited |
|---|---|---|
| `SUPPORTED` | The metric shifted in the asserted direction, at or above the frozen minimum score. | supporting IDs |
| `REFUTED` | The eligible metric shifted the *opposite* way. | contradicting IDs |
| `UNKNOWN` | Evidence is missing, stale, ineligible, too weak, context-mismatched, or the claim is causal. | none |

A composed hypothesis is either `ALL` (every predicate must hold) or `ANY` (at least one). A
causal claim, or a tenant/incident/run that doesn't match the ledger, comes back `UNKNOWN` by
construction. There's no prompt that talks its way past this, because the verdict is decided by
code that never reads the prompt.

## Quickstart

You need Python 3.12 and uv 0.11.17 (the lock/build tool, exact-pinned).

```bash
uv sync --locked
```

Run the hermetic gate. No database, no network, no credentials:

```bash
uv run --locked python -m unittest discover -s tests -p "test_*.py" -v
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src tests
uv run --locked python scripts/validate_project.py
```

## Run the service

`python -m incident_evidence_compiler` wires the persistence, LLM, and telemetry ports from
environment variables into the control plane plus an in-process worker loop (ADR 0016). Config
is environment-only and fail-fast: a missing or invalid value stops startup with a stable,
secret-free message instead of booting into a half-configured state.

```bash
# Credential-free smoke: in-memory store, non-model smoke client, no telemetry.
IEC_TOKENS=dev-token=tenant-a uv run --locked python -m incident_evidence_compiler
# serves 127.0.0.1:8000  (GET /health, GET /metrics)
```

```bash
# The real thing: PostgreSQL, Gemini on Vertex AI, RCAEval-backed demo telemetry.
IEC_TOKENS=prod-token=tenant-a \
IEC_PERSISTENCE=postgres IEC_DATABASE_URL=postgresql://iec@localhost/iec \
IEC_LLM_PROVIDER=vertex IEC_GEMINI_PROJECT=<gcp-project> IEC_GEMINI_LOCATION=us-central1 \
IEC_TELEMETRY=rcaeval IEC_RE2_ROOT=/path/to/RE2/RE2-OB \
uv run --locked python -m incident_evidence_compiler
```

| Variable | Default | Purpose |
|---|---|---|
| `IEC_TOKENS` | required | `token=tenant` pairs, comma-separated. Never logged. |
| `IEC_PERSISTENCE` | `memory` | `memory`, or `postgres` (then `IEC_DATABASE_URL` is required). |
| `IEC_LLM_PROVIDER` | `fake` | `fake` (non-model smoke), `developer` (`GEMINI_API_KEY`), or `vertex` (`IEC_GEMINI_PROJECT`). |
| `IEC_TELEMETRY` | `none` | `none`, or `rcaeval` (then `IEC_RE2_ROOT` points at an out-of-repo split). |
| `IEC_BIND_HOST` / `IEC_BIND_PORT` | `127.0.0.1` / `8000` | Listen address (the container image binds `0.0.0.0`). |

Or run the container. It's a multi-stage uv build, runs as a non-root user, and health-checks
`/health` with the standard library (no curl in the image):

```bash
docker build -t incident-evidence-compiler .
docker run --rm -p 8000:8000 -e IEC_TOKENS=dev-token=tenant-a incident-evidence-compiler
curl -fsS http://127.0.0.1:8000/health
```

One thing I want to be straight about: `IEC_LLM_PROVIDER=fake` is a labelled smoke client, not a
model, and `IEC_TELEMETRY=rcaeval` is a demo bridge over the benchmark, not a production
ingestion path (see [what it doesn't do](#what-it-doesnt-do-yet)). `/health` and `/metrics` are
open on purpose; put them behind your network boundary when you deploy.

## HTTP API

The control plane is built by `create_app(uow_factory=..., tokens=...)` in
[`api/app.py`](src/incident_evidence_compiler/api/app.py). Auth is a static bearer token mapped
to a tenant. Every data route is tenant-scoped, and a cross-tenant lookup returns `404`, not
`403`, so you can't probe for which investigations exist. `/health` and `/metrics` are the only
open routes.

| Method & path | Purpose | Success | Notable errors |
|---|---|---|---|
| `GET /health` | Liveness (open) | `200 {"status":"ok"}` | — |
| `GET /metrics` | Prometheus text (open, no tenant/PII labels) | `200 text/plain` | — |
| `POST /investigations` | Open an investigation (idempotent via `Idempotency-Key`) | `202 {"investigation_id"}` | `401`, `422 <code>` |
| `GET /investigations/{id}` | Status | `200 {"investigation_id","status"}` | `401`, `404 investigation_not_found` |
| `GET /investigations/{id}/report` | Verified report | `200 {...,"report":{...}}` | `404`, `409 report_not_ready` |

`POST /investigations` body:

```json
{
  "incident_id": "checkout-2026-07-18",
  "run_id": "run-1",
  "window": {
    "start": "2026-07-18T10:00:00Z",
    "injection": "2026-07-18T10:10:00Z",
    "end": "2026-07-18T10:20:00Z"
  }
}
```

The report you get back is the verification result:

```json
{
  "investigation_id": "…",
  "schema_version": "metric-shift-verification.v1",
  "report": {
    "hypothesis_id": "…",
    "composition": "any",
    "verdict": "supported",
    "reason": null,
    "predicate_results": [
      {
        "predicate_id": "p1",
        "verdict": "supported",
        "observed_direction": "increase",
        "supporting_evidence_ids": ["…"],
        "contradicting_evidence_ids": []
      }
    ],
    "supporting_evidence_ids": ["…"]
  }
}
```

Every error body is a flat `{"code": "<stable_code>"}`. No model text, no tenant data, no
internals cross the boundary.

## Optional integration checks

These are excluded from the hermetic gate because they need real infrastructure:

```bash
# PostgreSQL:
docker compose up -d
uv run --locked python -m unittest tests.test_persistence_postgres

# Live Gemini (Developer API key):
GEMINI_API_KEY=… uv run --locked python -m unittest tests.test_llm_gemini
```

## Reproduce the evaluation

The RCAEval RE2 data is never committed and lives outside the repo (ADR 0009). Point the loader
at your own extracted split:

```bash
# Deterministic baseline arm (no network):
uv run --locked python scripts/run_evaluation.py \
    --root /path/to/RE2/RE2-OB --arm baseline \
    --out docs/evaluation/re2-ob-baseline.json

# Verifier-gated Gemini arm (Vertex AI via ADC, or a Developer API key):
uv run --locked python scripts/run_evaluation.py \
    --root /path/to/RE2/RE2-OB --arm gemini \
    --provider vertex --project <gcp-project> --location us-central1 \
    --model gemini-2.5-flash --concurrency 4 \
    --out docs/evaluation/re2-ob-gemini.json
```

## Layout

```text
src/incident_evidence_compiler/
  domain/         # stdlib only: baseline, evidence ledger, verifier, change events, serialization
  persistence/    # psycopg repositories, in-memory fakes, migrations, SKIP LOCKED job queue
  llm/            # async LLMClient protocol, FakeLLMClient, untrusted parser, Gemini adapter
  application/    # framework-independent use-cases + the Worker + TelemetrySource port
  api/            # FastAPI control plane: routes, bearer auth, tenant scoping
  observability/  # stdlib-only Prometheus registry (counters, histograms, /metrics text)
  runtime/        # composition root: env config, wiring, worker loop, python -m entrypoint
  evaluation/
    rcaeval/      # bounded, label-safe RCAEval RE2 adapter + evaluation-only sidecar
    harness/      # baseline-input bridge, scoring, two-arm runner
scripts/          # validate_project.py (governance gate), run_evaluation.py
tests/            # hermetic unit/integration tests (fakes + deterministic LLM)
docs/             # decisions (ADRs), devlog, datasets, evaluation artifacts, architecture
```

## Principles (the ones I actually held)

- Write the contracts before the orchestration.
- Get a deterministic baseline working before adding a model.
- Treat `UNKNOWN` as a first-class answer, not a rounding error toward "no."
- PostgreSQL is the source of truth; everything else is a cache or a guess.
- Model output is untrusted input, always, everywhere.
- Every external call gets a deadline.
- A feature earns its complexity with a test or a measurement, or it doesn't ship.
- The README never claims more than a committed artifact can back up.

## What it doesn't do (yet)

I'd rather list this plainly than let you find it the hard way.

- **The held-out run is a single frozen pass.** RE2-TT was opened once (2026-07-19) for the
  numbers above; RE2-SS stays reserved. The held-out result is deliberately not re-run or tuned.
- **The LLM arm is deliberately blind to metric values.** Its low accuracy is the design working
  as intended (the verifier is the source of truth), not a bug I forgot to fix.
- **No production telemetry ingestion.** The service runs, but its only telemetry sources are the
  in-memory fake and a demo bridge over the RCAEval benchmark. A durable, tenant-owned telemetry
  ledger is future work. The worker also runs in-process; splitting it out is a later change.
- **Metrics, but no tracing.** There's a dependency-free Prometheus `/metrics` endpoint (per-stage
  latency, job outcomes, provider-timeout rate, token counts, verdict distribution, no PII).
  OpenTelemetry spans and cost estimation are deferred.
- **The baseline policy is a sensible default,** not a calibrated risk–coverage curve.
- **Single-node Postgres queue.** Redis admission control is deferred (ADR 0007).

## Roadmap

- Production telemetry ingestion beyond the RCAEval demo bridge, and an optional separate worker
  process.
- Make the evaluation harness stream cases (score-one-discard-one) so the full RE2-TT split runs
  without holding all cases in memory — the sealed run currently needs the whole split resident.
- OpenTelemetry spans per stage and an estimated-cost metric (the Prometheus counters and latency
  histograms already ship at `/metrics`).

## Provenance

This is an independent rewrite. No source is copied from `yashprogrammer/EnterpriseRAG_live`,
which I audited as a learning reference and cite in [`docs/provenance.md`](docs/provenance.md).

## License

Source, docs, and config are Apache-2.0 — see [`LICENSE`](LICENSE) and
[ADR 0008](docs/decisions/0008-apache-2.0-license.md). RCAEval dataset licensing is separate and
documented in [`docs/datasets/rcaeval-re2.md`](docs/datasets/rcaeval-re2.md); the raw benchmark
data is never committed.

## If you want to read further

- [`docs/decisions/`](docs/decisions/) — the 16 ADRs, where the real design arguments are.
- [`docs/devlog/`](docs/devlog/) — a phase-by-phase journal with the evidence behind each claim.
- [`docs/architecture/overview.md`](docs/architecture/overview.md) — components and trust
  boundaries in more detail.
- [`AGENTS.md`](AGENTS.md) — the operating contract for anyone (human or agent) working in here.
