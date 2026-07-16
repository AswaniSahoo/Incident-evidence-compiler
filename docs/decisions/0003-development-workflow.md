# ADR 0003: Development and Publication Workflow

- Status: Accepted
- Date: 2026-07-16

## Decision

Develop in numbered phases. Each phase uses a dedicated branch, narrow acceptance criteria, targeted tests, an independent review, a phase validation gate, a context update, and a devlog entry before acceptance.

## Git policy

- `main` marks accepted phase boundaries.
- Implementation occurs on `phase/<number>-<name>` or `feature/<name>`.
- Commits are logical and use conventional prefixes.
- Automated work stages explicit files.
- Shell and write require approval; hook regexes provide accident prevention rather than sandboxing.
- Automated shell pushes remain disabled. After explicit approval, publication uses dedicated provider tooling or a user-run Git command.
- Amend, force operations, destructive resets, and hook bypass require explicit approval.

## Agent policy

- The main agent coordinates product and architecture with Aswani.
- A separate agent implements a bounded slice when useful.
- Another agent reviews it independently.
- The main agent verifies tool output before accepting completion.
- Context summaries are aids, not evidence; code, tests, Git, and accepted ADRs are authoritative.

## Publication policy

Each phase devlog records the problem, first principle, considered alternatives, decision, implementation, experiment, failure, evidence, limitations, and next question. Public claims must link to reproducible artifacts.

## Phase gate

A phase is complete only when its acceptance criteria, relevant tests, lint/type checks, integration behavior, documentation, context, and devlog are verified. The exact checks expand with the codebase.
