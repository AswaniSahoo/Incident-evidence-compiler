# Devlog 0016, Fuzzing the untrusted boundaries and a documentation-honesty sweep

Status: implemented on `main`. Test-only plus documentation; no source, schema, or API change.

## 1. Problem

An external review of the repository (senior-engineer pass, read-only) surfaced three findings
worth acting on, and one of them was uncomfortable given this project's own rules.

The substantive one: every adversarial test at the two untrusted boundaries was a hand-picked
example. `tests/test_llm.py` covers oversized input, non-JSON, non-object JSON, empty input, bad
predicate structure, an out-of-allow-list signal, and too many predicates. That proves the cases the
author thought of. For a boundary whose entire contract is "treat this input as hostile", the cases
the author did not think of are the interesting ones.

The uncomfortable ones were documentation hygiene. The README badge claimed 325 passing tests when
the suite had 340, and the README said "the 17 ADRs" when there were 19. Both under-claimed rather
than over-claimed, so nothing was inflated, but a project whose stated principle is "the README
never claims more than a committed artifact can back up" should not be the thing a judge catches
drifting. Separately, the em-dash prohibition in the working rules was violated 263 times across 47
tracked files.

## 2. First principle

A typed-failure contract is only worth what it is tested against. The worker maps LLM-boundary
failures to a terminal outcome *because* it trusts that `parse_metric_hypothesis` raises only
`LLMValidationError` subclasses; if some other exception can escape, that trust is misplaced and the
failure is untyped in production. The same holds for `series_to_signals` and `PrometheusError`.
That contract is a property, not an example, so it should be tested as one.

Fuzz the value space, not the type space. `PrometheusPoint.value` is statically a `float`, and mypy
already forbids anything else, so generating a string there would test the type checker rather than
the code. The interesting inputs are the ones that are well-typed and still hostile.

## 3. Decision

Add `tests/test_fuzz_boundaries.py`: a standard-library randomized harness over the two boundaries,
with fixed seeds so a failure reproduces exactly instead of appearing once in CI and vanishing.

No new dependency, so no dependency ADR. The `hypothesis` property-testing library was considered
and rejected for this window: it would need its own dependency ADR under this project's governance,
and `random` plus fixed seeds captures the same invariant here at a fraction of the cost.

The generators cover random JSON, truncation mid-token (the streamed-response failure), duplicate
JSON keys, deep nesting, oversized input, hostile strings (path traversal, SQL, template and script
injection, and a direct "ignore previous instructions" override attempt), field-level mutation of a
well-formed proposal, and predicate-budget pressure on both sides of `MAX_PREDICATES`.

The assertions are the contract, not merely the absence of a crash:

- The parser returns a `HypothesisDocument` or raises an `LLMValidationError` subclass. Any other
  exception fails the test by name.
- A returned document never carries a signal outside the caller's allow-list, and never more than
  `MAX_PREDICATES` predicates.
- The mapper returns signals or raises `PrometheusError`, nothing else.
- Returned signals contain only finite samples (non-finite are gaps, dropped, never coerced, per
  ADR 0010), carry unique keys, and have a strictly increasing timeline.

## 4. Experiment, and the gap the first version missed

The first version passed immediately, which is exactly when a fuzz test should be distrusted. A
harness that only ever reaches the reject path proves nothing about the accept path, so the outcome
distribution was measured rather than assumed. Over 1,500 generated proposals:

| Outcome | Count |
|---|---|
| `ProposalSchemaError` | 1005 |
| `MalformedProposalError` | 319 |
| `ProposalTooLargeError` | 106 |
| accepted (valid document returned) | 29 |
| `EmptyProposalError` | 28 |
| `TooManyPredicatesError` | 13 |
| **`UnauthorizedEntityError`** | **0** |

Zero hits on the allow-list check, the one branch that carries the security guarantee. Random
mutation almost always broke the structure first, so the parser rejected the input long before it
reached the signal check. The generator was hitting the cheap validators over and over and never
reaching the expensive one.

The fix was a dedicated strategy: a structurally perfect proposal naming a *hallucinated* signal, a
plausible neighbour (`payment.errors`, `ledger_db.errors`), a case-flipped twin (`Checkout.Errors`),
or a whitespace-padded lookalike (`checkout.errors `). After it, over the same 1,500 cases:

| Outcome | Count |
|---|---|
| `ProposalSchemaError` | 884 |
| `MalformedProposalError` | 305 |
| **`UnauthorizedEntityError`** | **133** |
| `ProposalTooLargeError` | 111 |
| `EmptyProposalError` | 32 |
| accepted (valid document returned) | 20 |
| `TooManyPredicatesError` | 15 |

All six rejection types plus the accept path are now exercised. The mapper harness, over its own
1,500 cases, produces 1,057 `PrometheusError`, 314 empty results (every series was gaps), and 129
results carrying signals, so both its outcomes are covered too.

No production bug was found. That is the honest result: the boundaries held for every generated
input, which is a weaker claim than "we found and fixed a vulnerability" and a stronger one than
"the examples we wrote pass". Worth naming precisely, since one near miss did show up while reading
the code for this work: `parsing.py` catches `(KeyError, TypeError, ValueError)` around domain
construction, and that is safe only because `DomainValidationError` inherits from `ValueError`
(`domain/errors.py:15`). A domain error outside that hierarchy, such as `BaselineComputationError`,
which inherits `ArithmeticError`, would escape the LLM boundary untyped if it were ever raised on
this path. It is not raised there today, and the fuzz test would now catch it if that changed.

## 5. Reproducible evidence

```bash
uv run --locked python -m unittest tests.test_fuzz_boundaries -v
uv run --locked python -m unittest discover -s tests -p "test_*.py"
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src tests
uv run --locked python scripts/validate_project.py
```

Results: the two fuzz tests run in 0.1s over 3,000 generated inputs; the full hermetic gate is
**342 tests, OK, 10 skipped**; ruff clean, `ruff format` clean, strict mypy clean over 90 source
files, `project validation passed (full)`. `pyproject.toml` and `uv.lock` are unchanged, so the
stdlib-only test posture holds.

## 6. Documentation hygiene, same pass

- The README badge moved from a stale 325 to the verified count, and "the 17 ADRs" became 19.
- Em-dashes were removed repo-wide: 263 occurrences across 49 files, replaced by commas, hyphens, or
  full stops by context. Two wrapped-line artifacts (a comma stranded at the start of a continuation
  line, in ADR 0006 and ADR 0018) were fixed by hand afterwards. The full gate was re-run green after
  the sweep, and `git grep` for the character now returns nothing in tracked files.

## 7. Limitations

- Fixed seeds mean fixed coverage. This is a reproducibility trade: the suite explores the same
  3,000 inputs every run rather than new ones each time. Widening it is a matter of adding seeds.
- The harness stays inside the static types by design (see section 2), so it does not model a caller
  that violates the type contract; mypy is the control for that.
- Only the two untrusted *input* boundaries are fuzzed. The serializers and the verifier have
  hand-written adversarial tests (`AdversarialBoundaryTests`, `ReconstructionBoundaryTests`) but no
  randomized coverage yet.

## 8. Next question

The review also noted that identifier validation (`domain/identifiers.py:9-11`) is only "non-empty
string", with no per-field length bound, so the 65,536-character total proposal ceiling is the only
thing bounding any single identifier. Risk today is low, since those values never render as HTML and
no error path echoes them. Is a per-field bound worth adding as defense in depth, or is the total
ceiling plus the no-echo contract the right stopping point?
