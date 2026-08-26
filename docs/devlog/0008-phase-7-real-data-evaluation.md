# Devlog 0008, Phase 7: real-data integration and development evaluation

Status: implemented on branch `phase/07-real-data` (not yet merged). Finalized with
verified evidence at acceptance.

## Goal

Run the pipeline on real RCAEval RE2-OB data and measure it: a real-data integration path
(adapter → baseline inputs → worker → verified report) with leakage sanitation, and a
development evaluation of a deterministic baseline arm versus a verifier-gated Gemini arm,
with committed aggregate metrics (ADR 0014).

## First principle

Ground every published number in a real, reproducible run; keep separately-licensed data
out of the repository and CI; and never let ground-truth labels reach investigation code or
a committed artifact. Do not fabricate a result when infrastructure is unavailable.

## Smallest implemented slices

- **7a, integration:** an `evaluation/harness/baseline_inputs.py` bridge maps adapter
  signals to strictly-positive baseline inputs and a signal key to its service; an opt-in
  `skip_unparsable_cases` mode on the adapter tolerates the two trailing-empty-`time` cases
  (ADR 0010) and counts them. A hermetic end-to-end test flows the committed leakage fixture
  through the bridge and the worker and asserts no label or locator appears on any persisted
  evidence/report surface.
- **7b, evaluation:** `scoring.py` (Top-1/Top-3/MRR/abstention/invalid-ID, overall and
  answered-only) and `runner.py` (baseline arm; verifier-gated Gemini arm with bounded
  concurrency and transient-retry). `scripts/run_evaluation.py` runs an arm against an
  out-of-repo split and emits an aggregate, label-free JSON artifact under `docs/evaluation/`.

## Experiment and results

RE2-OB, 88 cases (2 skipped for a trailing empty `time` row):

| Arm | Top-1 | Top-3 | MRR | Abstention | Invalid evidence IDs |
|---|---|---|---|---|---|
| baseline (deterministic) | 0.932 | 0.989 | 0.959 | 0.000 | 0 |
| gemini-2.5-flash (Vertex) | 0.080 (0.159 answered) | 0.091 | 0.085 | 0.500 | 0 |

The deterministic baseline, which sees the metric values, localizes the injected service
strongly on the observable split. The Gemini arm receives only signal *names*, so it guesses
among ~72 signals and frequently proposes downstream symptoms; the deterministic verifier
gates those guesses, yielding 50% abstention and **zero** invalid evidence citations. This
is a faithful demonstration of "deterministic baseline before an LLM" and "model output is
untrusted," not a tuned showcase.

## What failed or changed (the real-integration debugging)

The first live Gemini run returned 100% abstention. Diagnosis (with the masked provider
error surfaced via throwaway diagnostics, since deleted) found a chain of real defects, each
fixed minimally behind the unchanged strict parser:

1. **Vertex misrouting:** an ambient `GOOGLE_GENAI_USE_VERTEXAI=true` from a local gcloud SDK
   rerouted the API-key client to Vertex (401/403). Fixed by pinning `vertexai=False` on the
   API-key path and adding an explicit `from_vertex` path for the paid Vertex backend.
2. **Client-lifetime bug (root cause):** the adapter retained only `client.aio.models`, so
   the parent `genai.Client` was garbage-collected and closed its HTTP transport, every call
   failed with "Cannot send a request, as the client has been closed." Fixed by retaining the
   whole client.
3. **Markdown fences:** the model wraps JSON in ```` ```json ```` blocks; the adapter now
   unwraps them before the strict parser.
4. **Prompt vocabulary:** the model emitted `"composition": "AND"`, `"expected_direction":
   "UP"`, and a prose `semantics`; the prompt now specifies the exact enum values and
   requires the ids be echoed.
5. **Rate-limit noise:** at high concurrency, Vertex 429s were miscounted as abstentions
   (inflating abstention to 87.5%). Transient retry with backoff restored the honest 50%.

`gemini-3.5-flash` was requested but is not served on this Vertex project (404); it exists
only on the quota-limited Developer API. `gemini-2.5-flash` is the working Vertex model.

## Reproducible evidence

- Baseline: `uv run python scripts/run_evaluation.py --root <RE2-OB> --arm baseline --out
  docs/evaluation/re2-ob-baseline.json`, deterministic, no network.
- Gemini: same with `--arm gemini --provider vertex --project <id> --location us-central1
  --model gemini-2.5-flash --concurrency 4`, using ADC on a billing-enabled project.
- Hermetic gate green: `compileall`; unittest (with the PostgreSQL and Gemini-live tests
  skipped); `ruff check`; `ruff format --check`; strict `mypy`; `python
  scripts/validate_project.py` (full) under Phase 7; `git diff --check`.
- No raw data, archive, sidecar, or per-case label was committed; only aggregate metrics.

## Limitations

RE2-OB is the observable split; RE2-TT stays sealed and RE2-SS reserved, so these are
development numbers, not a held-out claim. The Gemini arm is intentionally blind to metric
values; its low accuracy reflects that design, not a defect. The baseline policy is a
documented development default, not a calibrated risk–coverage curve (cut per ADR 0007).

## Next question

Whether a richer prompt (or giving the model ranked candidate context without leaking the
answer) materially improves the LLM arm, and whether a single sealed RE2-TT run is
authorized once the OB numbers are accepted.
