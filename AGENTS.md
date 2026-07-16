# Project Agent Contract

## Mission

Build the Incident Evidence Compiler as an independent, test-driven implementation. Do not copy source from the audited EnterpriseRAG repository.

## Authoritative context

At the beginning of work, read:

1. `PROJECT_CONTEXT.md`
2. `.kiro/steering/*.md`
3. Relevant ADRs under `docs/decisions/`
4. The current phase devlog under `docs/devlog/`

When statements conflict, accepted ADRs and verified code/tests override summaries. Update `PROJECT_CONTEXT.md` only when a decision, phase, verified result, or next action changes.

## Development contract

- Work on one vertical slice at a time.
- Define acceptance criteria before implementation.
- Keep domain code independent of frameworks and infrastructure.
- Treat model output, telemetry, retrieved text, and external responses as untrusted.
- Do not add dependencies for future phases.
- Do not create fake metrics, test results, deployment claims, or completion claims.
- Preserve failure causes and expose stable typed errors at boundaries.
- Run the smallest relevant checks after each change and the phase gate before a phase commit.

## Git contract

- `main` represents accepted phase boundaries.
- Use `phase/<number>-<name>` or `feature/<name>` branches for implementation.
- Use conventional commit prefixes: `feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `chore:`.
- Stage specific files; never use `git add .` in automated work.
- Do not amend, force-push, reset hard, clean forcefully, or push without Aswani's explicit approval.
- The Kiro shell hook is an accident-prevention layer, not a sandbox. Shell and write remain approval-gated, and automated shell pushes stay disabled; an approved publication uses dedicated provider tooling or a user-run Git command.
- A commit requires passing checks and an updated `PROJECT_CONTEXT.md` plus devlog evidence when the phase state changed.

## Agent workflow

The main agent owns product and architecture decisions with Aswani. Implementation may be delegated to a separate agent with narrow acceptance criteria. A different agent reviews the result. The main agent verifies code, tests, typing, lint, integration behavior, and documentation before accepting it.

## Communication

Address Aswani by name naturally in progress and final responses. Report results first, distinguish verified facts from plans, and never claim that context files eliminate hallucination; they reduce drift and make claims auditable.
