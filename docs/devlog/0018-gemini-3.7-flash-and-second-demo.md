# 0018: gemini-3.7-flash on RE2-OB, and a second live demo run

Date: 2026-08-31 (recorded 2026-09-01)

## What ran

1. The two-arm evaluation harness against the RE2-OB development split, gemini arm, model
   `gemini-3.7-flash`, under the same frozen configuration as the 2026-07 runs. The invocation
   followed the documented reproduce command (`scripts/run_evaluation.py --arm gemini` with
   `--model gemini-3.7-flash`); the exact command line was not retained, and the artifact's
   embedded `config` block is the authoritative record of the effective configuration
   (`minimum_score` 3.0, same floors and margins as
   [`re2-ob-gemini.json`](../evaluation/re2-ob-gemini.json)).
2. The compose demo (`scripts/demo_live_investigation.py`) once more against Vertex
   `gemini-2.5-flash`, injection at 2026-08-30T22:10:59Z.

RE2-TT was not touched. The sealed held-out protocol remains executed exactly once (2026-07-19).

## Evidence

- Artifact: [`docs/evaluation/re2-ob-gemini-3.7-flash.json`](../evaluation/re2-ob-gemini-3.7-flash.json).
  88 cases, 2 skipped. Top-1 0.068 (0.125 answered), Top-3 0.068, MRR 0.068, abstention 0.455
  (40 of 88), invalid evidence IDs 0. Label-free aggregates only, per ADR 0009.
- Demo transcript: verbatim in the README under "Same system, different day (2026-08-31)". The
  model proposed two checkout predicates; both resolved `unknown` (`weak_evidence`); the overall
  verdict is `unknown`. Zero false assertions.
- Ranking observation: the report's `baseline_ranking` field (ADR 0019) placed both `bank_router`
  signals first, well clear of the rest. This was read from the live report during the run; the raw
  report JSON was not saved before `docker compose down -v` discarded the volume, so the README
  states the observation without exact scores and this entry records that the underlying payload
  was not retained. The field itself is asserted by `tests/test_api.py` and documented in the
  README API section, so any rerun reproduces the shape.

## Reading

A newer model generation does not outperform the older one when both are value-blind: 3.7 Flash
scored below 2.5 Flash on Top-1 (0.068 vs 0.080) with slightly lower abstention. The gate metric,
invalid evidence citations, stayed at zero for both models, which is the property the system
actually depends on. The 2026-08-31 demo is the stronger live demonstration of the thesis: the
model was entirely wrong, the verifier accepted nothing, and the deterministic ranking localized
`bank_router` without the model. The run was reported as it happened, per the demo honesty
guardrails: no re-roll for a prettier verdict.
