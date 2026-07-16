# Phase 1: A Baseline Before an AI Investigator

- Date: 2026-07-16
- Status: In progress

## Problem

An incident system cannot measure whether an LLM helps unless a deterministic, label-safe baseline exists first. The benchmark itself can also leak the answer through directory names before any telemetry is analyzed.

## First principle

Separate three things that are often collapsed: observed telemetry, evaluation ground truth, and a diagnostic ranking. Only telemetry belongs in investigation input. Ground truth is used after prediction, and a ranking is not proof of causality.

## Alternatives

1. Start with Gemini and evaluate generated reports later.
2. Reuse RCAEval's pandas-based baseline implementation directly.
3. Build a small standard-library domain and metric-shift baseline, then compare future systems against it.

## Decision

Choose the third option. Keep the runtime dependency-free, make abstention explicit, and use tiny synthetic fixtures until the pinned archive is manually provided. Investigation cases receive random UUIDs; source locators and labels remain in an evaluation-only sidecar.

## Research evidence

- RCAEval release `1.2.0` resolves to commit `bc49dbd85bd14032101fb9a69a5a37e9d6d55178`.
- RE2 contains 270 multi-source cases across Online Boutique, Sock Shop, and Train Ticket.
- The evaluator derives answers from `<service>_<fault>` directory names.
- RE2-OB is 1,191,025,569 bytes and RE2-TT is 2,801,345,134 bytes.
- Zenodo reports metadata publication date 2024-01-03 and record creation timestamp 2025-01-03; these are distinct fields.
- The pinned upstream repository says the authors' datasets are MIT, while Zenodo metadata says `cc-by-4.0`; both notices are recorded and raw data will not be redistributed.

## Plan-review findings

The first independent plan review returned `NEEDS_CHANGES`. It identified a Phase 0 validator that would reject Phase 1 files, an enumerable path-derived ID, under-specified baseline math, ambiguous discovery fallback, weak leakage-channel coverage, and a missing clean-checkout tool path. The plan now requires phase-aware governance, locked `uv` execution, random case IDs, an evaluation-only sidecar, exact formula semantics, per-case metric preference, and negative tests over serialization, representations, logs, and errors.

## Planned experiment

Create synthetic cases with known pre/post metric shifts, weak shifts, ties, missing windows, malformed rows, oversized inputs, and label-bearing paths. Verify deterministic ranking, abstention, bounded failure, sealed-split denial, and zero ground-truth leakage.

## Expected failure modes

- A zero-variance pre-window can inflate a score unless scale floors are explicit.
- Equal shifts can create nondeterminism unless the tie-break is canonical.
- A loader can leak labels through paths, object representations, logs, or error messages.
- Large CSV fields or case counts can exhaust memory unless every layer has a bound.
- A benchmark score can be invalid if the held-out split is inspected during tuning.

## Evidence

Implementation and validation evidence are pending.

## Limitations

No RCAEval archive has been downloaded or inspected directly. The initial loader contract is based on the pinned evaluator and official multi-source sample; archive-specific differences must fail explicitly rather than silently fall back.

## Next question

Can a small robust-shift baseline identify useful suspects while abstaining honestly when telemetry is weak or ambiguous?
