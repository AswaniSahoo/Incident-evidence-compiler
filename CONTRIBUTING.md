# Contributing

## Before changing code

1. Read `PROJECT_CONTEXT.md` and the relevant ADRs.
2. Create a phase or feature branch.
3. State acceptance criteria and failure behavior.
4. Confirm that new dependencies and infrastructure are needed now.

## Implementation

- Prefer a working vertical slice over broad scaffolding.
- Keep domain contracts independent of frameworks.
- Add tests with behavior, not after it.
- Use deterministic fakes for external AI and telemetry services.
- Preserve typed error causes at boundaries.
- Update documentation only with verified behavior.

## Validation

Run the targeted checks for changed behavior and the current phase gate. Phase 1 uses the
locked commands documented in `README.md`; begin with `uv sync --locked`, run unittest,
Ruff check/format, strict mypy, project validation, and Kiro agent validation.

## Commits

Use conventional prefixes and stage explicit files. A commit should represent one reviewable idea and include tests/documentation needed to verify that idea. Do not bypass hooks or rewrite published history.

## Review

Reviewers check correctness, failure semantics, security boundaries, tests, unnecessary complexity, and documentation accuracy. Style-only feedback should not obscure behavioral risks.
