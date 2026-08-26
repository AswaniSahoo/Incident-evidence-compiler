# ADR 0014: Real-data integration and development evaluation (Phase 7)

- Status: Accepted
- Date: 2026-07-18
- Decision owners: Aswani and the project orchestrator

## Context

Phases 0–6 delivered the deterministic domain, persistence, the LLM provider boundary, and
the async control plane/worker, all verified hermetically against synthetic fixtures and a
deterministic fake. Phase 7 (per `MASTER-PLAN.md`) turns the pipeline on **real** RCAEval
RE2-OB data and measures it: a real-data integration path plus a development evaluation of a
deterministic **baseline** arm and a verifier-gated **Gemini** arm. RE2-OB is stored and
extracted outside the repository and is never committed (ADR 0009); CI stays hermetic.

Research against the tree surfaced the concrete gaps this ADR resolves:

1. The adapter yields `InvestigationCase`s carrying `MetricSignal`s but no per-signal
   `absolute_scale_floor`, which the baseline requires to be strictly positive.
2. There was no mapping from a ranked signal to a root-cause *service*, and no scoring.
3. `RcaevalAdapter.load` is all-or-nothing; two known RE2-OB cases fail the strict parser on
   a trailing empty-`time` row (a deferred open decision from ADR 0010).
4. The Gemini adapter had never made a real call; the first real run exposed several
   integration defects (below).

## Decision

### 1. A label-safe evaluation harness in the evaluation layer

A new `evaluation/harness/` package scores predictions against ground truth. Ground truth
lives only in the evaluation `EvaluationSidecar` and is consumed only here; it is never
passed to investigation code. The harness depends on `domain` and `llm` but not on
`application`/`persistence`, and performs no database I/O.

### 2. Signal → service mapping and baseline inputs

- A signal key maps to its owning service as everything before the final underscore
  (`checkoutservice_latency-90 → checkoutservice`, `frontend-external_workload →
  frontend-external`). This uses only telemetry column names, never a label.
- Each signal's `absolute_scale_floor` is derived from its own magnitude:
  `max(1e-9, 0.05 · median(|value|))`, so it scales with the signal and never collapses to
  zero. The evaluation `BaselinePolicy` is `minimum_points_per_window=2, minimum_score=3.0,
  minimum_margin=0.0, relative_scale_floor=0.0`. These are development-set defaults, not a
  published calibration curve (calibrated abstention remains cut per ADR 0007).

### 3. Metrics

Top-1 / Top-3 root-cause-service accuracy, MRR, abstention rate, and invalid-evidence-ID
count, reported both *overall* (abstention counts as a miss, reflecting coverage) and
*answered-only* (over cases where the system committed). An abstention is scored as an empty
prediction. Metrics are aggregate and label-free.

### 4. Two arms

- **baseline**, deterministic, no network: rank metric shifts and predict the services of
  the ranked candidate signals.
- **gemini**, the full restricted-hypothesis pipeline: compile the evidence ledger, ask an
  `LLMClient` for hypotheses over the allow-listed signals, parse the untrusted output,
  verify it deterministically, and predict the services of the signals the verifier
  `SUPPORTED` (ranked by baseline suspicion). Any untrusted-output failure is a genuine
  abstention; transient provider failures are retried with backoff so infrastructure noise
  is not miscounted as model abstention.

### 5. Additive, opt-in tolerance for unparsable cases

`RcaevalAdapter.load(..., skip_unparsable_cases=False)` gains an opt-in mode that skips and
counts per-case parse failures (the two trailing-empty-`time` RE2-OB cases). The default
stays strict, so the hermetic gate and all Phase 1 tests are unchanged. `EvaluationBatch`
gains an additive `skipped_case_count` field (default 0).

### 6. Gemini adapter fixes discovered during real integration

The first real Gemini calls exposed defects, each fixed minimally and behind the unchanged
strict parser (the security boundary):

- **Client lifetime (root-cause bug):** the SDK adapter held only `client.aio.models`, so
  the parent `genai.Client` was garbage-collected and closed its HTTP transport, failing
  every request with "Cannot send a request, as the client has been closed." The adapter now
  retains the whole client.
- **Developer-API pinning:** `from_api_key` passes `vertexai=False` so an ambient
  `GOOGLE_GENAI_USE_VERTEXAI=true` / `GOOGLE_CLOUD_PROJECT` (from a local gcloud SDK) cannot
  reroute an API-key client to Vertex, which rejects API keys.
- **Vertex path:** a new `from_vertex(project, location, ...)` uses Application Default
  Credentials for the paid Vertex backend.
- **Markdown fences:** the model wraps JSON in ```` ```json ```` fences; the adapter unwraps
  them before the (still strict) parser sees the text.
- **Prompt vocabulary:** the prompt now states the exact enum values (`semantics`,
  `composition`, `expected_direction`) and requires the ids be echoed, so valid output
  parses.
- **Configurable model/deadline** and eval-runner **bounded concurrency + transient retry**.

### 7. Committed artifacts and leakage

Only aggregate, label-free metrics JSON is committed, under `docs/evaluation/` (the
`.gitignore`d `artifacts/` and `eval/results/` are for local run outputs). No per-case
ground truth is emitted, so no dataset answer labels are redistributed (ADR 0009 preserved).
Sanitation tests assert that no label or source locator appears on the persisted evidence,
report, or aggregate surfaces.

### 8. No new dependencies

The harness and CLI are standard-library only; `google-genai` (Phase 5) is reused. The
phase-aware validator extends to Phase 7 with no new approved runtime dependency.

## Verified results (2026-07-18, RE2-OB, 88 cases; 2 skipped: trailing-empty-`time`)

| Arm | Top-1 | Top-3 | MRR | Abstention | Invalid evidence IDs |
|---|---|---|---|---|---|
| baseline (deterministic) | 0.932 | 0.989 | 0.959 | 0.000 | 0 |
| gemini-2.5-flash (Vertex, verified) | 0.080 (0.159 answered) | 0.091 | 0.085 | 0.500 | 0 |

The baseline was run locally with no network; the Gemini arm was run against Vertex AI on
Aswani's project with real credits. Numbers are measured, not estimated.

## Consequences

### Positive

- The deterministic baseline localizes the injected service well on the observable split,
  demonstrating "deterministic baseline before an LLM."
- The verifier gates unsupported LLM guesses: 50% abstention and **zero** invalid evidence
  IDs, demonstrating "model output is untrusted."
- The `TelemetrySource` port (ADR 0013) let real data flow to the worker with no core change.

### Cost / limitations

- The LLM arm receives only signal *names*, not the metric values, so it guesses among ~72
  signals and often points at downstream symptoms; on this metric it underperforms the
  baseline. A richer prompt is future work, not a v1 gate.
- RE2-OB is the observable (easiest) split; RE2-TT stays sealed and RE2-SS reserved. These
  are development-set numbers, not a held-out claim.
- The evaluation baseline policy is a documented default, not a calibrated curve.

## Rejected alternatives

- **Commit per-case results** (would redistribute dataset answer labels; violates ADR 0009).
- **Weaken the untrusted-output parser to accept fenced/loose JSON** (the parser is the
  security boundary; fences are unwrapped in the provider adapter instead).
- **Feed the model the metric shift magnitudes** (would leak the baseline's answer and make
  the arm comparison meaningless).
- **Tune thresholds to inflate the baseline number** (dishonest; defaults are documented).
