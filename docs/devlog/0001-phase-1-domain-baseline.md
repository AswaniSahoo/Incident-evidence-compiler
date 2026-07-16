# Phase 1: A Baseline Before an AI Investigator

- Date: 2026-07-16
- Status: Complete

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
- Large CSV fields, rows, or case counts can exhaust memory unless every layer has a bound.
- A benchmark score can be invalid if the held-out split is inspected during tuning.

## Implementation evidence before first review

The uncommitted implementation was exercised without downloading RCAEval archives, configuring a remote, committing, or pushing.

- `uv sync --locked` completed with eight resolved development/build packages and no runtime dependencies.
- Compilation, all 70 then-current unit tests, Ruff check and format, strict mypy over 22 source files, the full project validator, Kiro agent validation, and `git diff --check` passed.
- `git remote -v` produced no output.

## First implementation review

The independent `gpt-5.6-sol` implementation review returned `NEEDS_CHANGES` despite the passing gates. It found two major defects:

1. The phase-aware validator did not preserve the accepted Phase 0 CI command and immutable-action contract.
2. `max_columns` checked the header but did not reject an over-wide malformed data row before retaining parsed rows.

The review also found stale evidence: unlocked commands in `PROJECT_CONTEXT.md`, premature completion status, an incorrect 69-test count, a broken sentence, and unsupported graph-based claims. Both major defects were corrected: CI validation now selects exact command and immutable-action contracts by phase, and CSV parsing now scans logical record width before `csv.reader`, processes rows incrementally, and checks every materialized row against `max_columns`. Regression tests cover the accepted Phase 0 workflow, an over-wide data row beneath an in-bounds header, and quoted delimiters. The stale evidence was removed rather than carried forward.

## Final validation

Aswani directed the work to avoid a repeated-review loop after the concrete findings were fixed. No additional independent-review verdict is claimed. Completion is based on the corrected implementation and this single final local gate:

- `uv sync --locked` passed with eight resolved development/build packages and no runtime dependencies.
- `uv run --locked python -m compileall -q src scripts .kiro/hooks tests` passed.
- `uv run --locked python -m unittest discover -s tests -p "test_*.py" -v` passed all 73 tests.
- `uv run --locked ruff check .` and `uv run --locked ruff format --check .` passed with 24 files formatted.
- `uv run --locked mypy src tests` passed in strict mode over 22 source files.
- `uv run --locked python scripts/validate_project.py` reported `project validation passed (full)`.
- `kiro-cli agent validate --path .kiro/agents/incident-orchestrator.json` exited zero.
- `git diff --check` passed and `git remote -v` produced no output.

## Limitations

No RCAEval archive has been downloaded or inspected directly. The initial loader contract is based on the pinned evaluator and official multi-source sample; archive-specific differences must fail explicitly rather than silently fall back.

## Next question

After the review findings are fixed and Phase 1 is approved, how does the deterministic baseline perform on a manually supplied RE2-OB archive without changing the sealed TT policy or leaking evaluation labels?
