# Devlog 0011 — Step 4: the one sealed RE2-TT held-out run

Status: executed once on 2026-07-19 on branch `step/04-sealed-tt-eval`. Freeze commit `c7823cc`;
results commit `59209e0`. This is the reported held-out number and will not be re-run.

## Goal

Convert the RE2-OB development result into a single held-out number on the sealed RE2-TT split,
run exactly once against a frozen configuration — the last credibility upgrade before the README
can claim a held-out accuracy. Governed by `docs/evaluation/re2-tt-sealed-protocol.md`.

## The enabling seam (TDD)

`scripts/run_evaluation.py` gained a `--sealed-confirm "<reason>"` flag. When `--split TT` is
requested it builds a `SealedSplitPermit` via `authorize_sealed_split(confirmed=True, reason=...)`
and passes it to `RcaevalAdapter.load`; without a non-empty reason the CLI fails closed
(`SystemExit`). OB/SS paths are unchanged. Three tests (written first, watched fail) assert TT is
denied without the flag, permitted with a reason, and that development splits need no permit. The
domain guard was already unforgeable (object-identity `_PERMIT_TOKEN` in `ids.py`); this is only
the thin outer CLI gate. Committed as its own slice at `c7823cc`, the frozen run commit.

## Freeze

Config taken verbatim from the accepted RE2-OB run (min_score 3.0, min_points 2, margins/floors,
`gemini-2.5-flash`, unchanged `_build_prompt`). Verified byte-for-byte against the committed
`re2-ob-baseline.json` config before running. No tuning against TT, before or after.

## Data acquisition

RE2-TT.zip pulled from Zenodo record 14590730, md5 `a7fbcd1ada406067dcc50771ae398408` and byte
count `2801345134` both verified exact, extracted to a directory named `RE2-TT` outside the repo
root (ADR 0009 guardrail intact). Never committed.

## The blocker: MemoryError (root-caused, not fixed)

Both arms first crashed with `MemoryError`. Root cause (measured, not guessed): `RcaevalAdapter`
materializes all 90 cases into one in-memory `EvaluationBatch` before scoring — ~524k
`MetricPoint` objects/case, ~42 MB/case, ~3.8 GB tracked / ~5–6 GB RSS for the full split. The
dev machine had ~1.6 GB free of 15.7 GB. `--limit` does not help: it trims scoring, which runs
after the full load. The computation is already per-case and `aggregate` is an order-independent
fold, so the retention is incidental. Decision (Aswani): keep the frozen code as-is and free RAM
(ran with ~8 GB free) rather than refactor before the sealed number. Proper fix — a streaming
score-one-discard-one path, provably score-identical by reproducing the OB baseline JSON — is on
the README roadmap and deferred. Vertex connectivity was probed with one live call first, so an
auth failure could not masquerade as a real all-abstention result.

## Held-out results (90 cases, 0 skipped, 0 invalid evidence IDs)

| Arm | Top-1 | Top-3 | MRR | Abstention |
|---|---|---|---|---|
| baseline (deterministic) | 0.766667 | 0.877778 | 0.832565 | 0.000000 |
| gemini (verifier-gated) | 0.155556 | 0.155556 | 0.155556 | 0.577778 |

Gemini answered 38/90; answered-only Top-1 0.368421. Reading: the deterministic baseline
localizes the unseen train-ticket faults well (Top-1 0.77); the verifier-gated arm stays
conservative — it abstained on 52/90 rather than assert an unverified cause and again emitted
zero invalid evidence citations. Accuracy drops from the dev split, the honest direction for an
unseen system. The fail-closed design is working as intended, not regressing.

## Evidence

- `docs/evaluation/re2-tt-baseline.json`, `docs/evaluation/re2-tt-gemini.json` (aggregate,
  label-free; `dataset.split = "TT"`).
- `docs/evaluation/re2-tt-sealed-protocol.md` results log + freeze commit.
- README held-out table. Governance validator passes (full); no leakage in the artifacts.
