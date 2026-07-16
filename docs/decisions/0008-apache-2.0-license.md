# ADR 0008: Apache-2.0 license for the public repository

- Status: Accepted
- Date: 2026-07-17
- Decision owners: Aswani and the project orchestrator

## Context

ADR 0007 committed to publishing this repository publicly on Day 1 of the two-week sprint and
made publication conditional on first selecting and recording a public license (the README
previously blocked publication until that decision existed). The repository is an independent
rewrite (ADR 0001) with no inherited upstream license. It is a portfolio and learning project
that should be freely readable, reusable, and safe to contribute to, while giving both the author
and downstream users an explicit patent grant and a clear liability disclaimer.

RCAEval dataset licensing is a separate matter and is unaffected by this decision: raw benchmark
data is never committed or redistributed, and its upstream terms are documented in
`docs/datasets/rcaeval-re2.md`.

## Decision

License the repository's own source, documentation, and configuration under the Apache License
2.0. Add the canonical license text as `LICENSE` with a `Copyright 2026 Aswani Sahoo` notice in
the appendix. Update the README to state the license and remove the publication block.

## Consequences

### Positive

- Permissive reuse with an explicit patent grant and a clear warranty/liability disclaimer —
  stronger contributor and user protection than MIT for a project that may attract contributions.
- Publication is unblocked per ADR 0007; every pushed commit still passes the phase gate.
- Compatible with the standard-library-only runtime and common downstream licenses.

### Cost

- Apache-2.0 carries slightly more ceremony than MIT (NOTICE conventions, change notices in
  derivatives), which is acceptable for a public production-oriented project.

## Rejected alternatives

- **MIT**: simpler, but no explicit patent grant. Rejected for a project intended to demonstrate
  production-grade practices.
- **No license / all rights reserved**: blocks the build-in-public goal and reuse. Rejected.
- **Copyleft (GPL family)**: unnecessary reciprocity friction for a portfolio library. Rejected.
