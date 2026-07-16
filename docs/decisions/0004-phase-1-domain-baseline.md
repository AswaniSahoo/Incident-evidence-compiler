# ADR 0004: Phase 1 Domain Baseline

- Status: Accepted
- Date: 2026-07-16

## Context

The production architecture needs a stable core before APIs, databases, workers, or Gemini are introduced. RCAEval encodes ground truth in directory names, so a convenient loader can silently leak answers into investigation inputs.

## Decision

Phase 1 delivers a framework-independent domain package, a deterministic metric-shift baseline, and a bounded RCAEval RE2 adapter. It does not implement causal verification, LLM generation, persistence, authentication, or network services.

## Domain contracts

The domain owns:

- Validated tenant, incident, run, evidence, and opaque case identifiers
- UTC incident windows and injection timestamps
- Canonical metric signals and finite timestamped points
- Ranked suspicion candidates with replayable score components
- Explicit baseline abstention reasons

The baseline output is a diagnostic ranking, not a causal claim. `SUPPORTED`, `REFUTED`, and `UNKNOWN` remain reserved for the later deterministic hypothesis verifier.

## Exact baseline semantics

For each signal, points must be strictly timestamp ordered. Signal collection order is irrelevant.

Given an incident window with `start <= injection < end`:

- Pre-injection points satisfy `start <= observed_at < injection`.
- Post-injection points satisfy `injection <= observed_at < end`.
- All points in those bounded intervals are used.
- Both windows require at least `minimum_points_per_window` points.
- `pre_median = median(pre_values)`.
- `post_median = median(post_values)`.
- `pre_mad = median(abs(value - pre_median) for value in pre_values)`.
- `scale = max(1.4826 * pre_mad, absolute_scale_floor, relative_scale_floor * max(abs(pre_median), absolute_scale_floor))`.
- `signed_score = (post_median - pre_median) / scale`.
- `suspicion_score = abs(signed_score)`.

`absolute_scale_floor` has the signal's units and must be positive. `relative_scale_floor` is dimensionless and non-negative. The configured floors, score threshold, margin threshold, and minimum point count are included in the result for replay.

Candidates are sorted by descending `suspicion_score`, then ascending canonical signal key. A single eligible candidate has an infinite lead. The baseline emits a ranking only when `top_score >= minimum_score` and, when a runner-up exists, `top_score - second_score >= minimum_margin`; both comparisons are inclusive. Otherwise it returns a typed abstention reason.

Tests cover signal-order permutations, canonical ties, injection-boundary points, zero and negative pre-medians, a single candidate, and values exactly on thresholds.

## Dataset and leakage boundary

- Pin RCAEval release `1.2.0` at commit `bc49dbd85bd14032101fb9a69a5a37e9d6d55178`.
- Treat RE2-OB as development/calibration data.
- Treat RE2-TT as sealed evaluation data; loading it requires an explicit override.
- Keep RE2-SS reserved and outside Phase 1 scoring.
- Commit only metadata and synthetic fixtures, never raw RCAEval archives or extracted telemetry.
- Keep source locators and ground truth in an evaluation-only sidecar that investigation code never receives.
- Assign a random UUID case identifier at the evaluation boundary. The mapping is local, ignored, and persisted only when replay is required; tests inject a deterministic ID factory.
- Custom representations, exceptions, and logging expose opaque IDs and stable error codes, never source paths or labels.
- Bound file bytes, rows, columns, field length, and discovered cases; reject malformed or non-finite values explicitly.

The adapter intentionally uses a safer per-case preference: in each case directory prefer `data.csv`, otherwise use `simple_metrics.csv`. This differs from RCAEval's global fallback and is covered by a mixed-tree fixture.

## Package, governance, and tooling

Use a `src/incident_evidence_compiler` package with standard-library runtime code. Unit tests use `unittest`. `pyproject.toml` and `uv.lock` pin Ruff `0.15.13`, mypy `2.1.0`, and the selected build backend; there are no application runtime dependencies.

Phase 1 must make governance phase-aware: remove `src`, `pyproject.toml`, and `uv.lock` from the Phase 0-only forbidden set; add validator fixtures for the Phase 1 contract; and update CI to install the locked environment and run all gates through `uv run`. A clean checkout must execute `uv sync --locked` before tests, so the `src` package is installed rather than injected through `PYTHONPATH`.

## Acceptance criteria

1. Domain value objects reject empty identifiers, naive timestamps, invalid intervals, non-finite values, and out-of-order points.
2. The exact baseline formula is deterministic, ranks a synthetic shifted signal first, and abstains for insufficient, weak, or ambiguous evidence.
3. A machine-readable manifest records authoritative URLs, retrieval date, release/commit, archive sizes/checksums, and both upstream license notices.
4. The loader enforces bounds, uses documented per-case metric preference, keeps TT sealed by default, and does not require pandas.
5. Investigation serialization, representations, captured logs, and malformed-input errors contain no source locator, injected service/fault label, or ground-truth object.
6. A clean checkout passes locked-environment sync, compilation, unit tests, Ruff, mypy, project governance, and Kiro agent validation.
7. Independent review verdict and exact command evidence are recorded in the Phase 1 devlog.
8. The final local gate verifies that `git remote -v` is empty. The no-push rule remains a process constraint, not a historical test claim.

## Subphase commits

1. `docs: define phase 1 domain baseline`
2. `feat: add deterministic incident baseline`
3. `feat: add bounded RCAEval loader`
4. `docs: record phase 1 validation evidence`
