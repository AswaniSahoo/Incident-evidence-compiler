# ADR 0001: Independent Rewrite

- Status: Accepted
- Date: 2026-07-16
- Decision owners: Aswani and the project orchestrator

## Context

The starting EnterpriseRAG repository is a clean clone of a public GitHub repository with no license file. Its implementation also has structural correctness, security, testing, and documentation defects. Incremental modification would preserve unclear provenance and accidental architecture.

## Decision

Build the Incident Evidence Compiler in a new Git repository without copying upstream source or history. Keep the clone as a read-only audit reference and cite it in project provenance.

## Consequences

### Positive

- Clear authorship and learning ownership.
- Contracts and tests can precede infrastructure.
- No accidental inheritance of unsafe behavior or unsupported claims.
- Git history tells the redesign story phase by phase.

### Cost

- Useful components must be independently reimplemented.
- Initial progress appears slower than editing the clone.
- A public license still requires a separate decision.

## Rejected alternative

Fork and patch the upstream implementation. Rejected because no explicit upstream license file exists and because the desired architecture is materially different.
