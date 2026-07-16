# Phase 0: Foundation Before Features

- Date: 2026-07-16
- Status: Complete

## Problem

The starting point was a public EnterpriseRAG clone that looked feature-rich but had no test suite, unsafe orchestration and SQL boundaries, blocking calls in async endpoints, mismatched documentation, and no explicit license file. Editing it directly would blur authorship and preserve accidental design.

## First principle

Before optimizing an AI system, establish what code we own, what problem it solves, which component is trusted to make each decision, and how claims will be verified.

## Alternatives

1. Patch the clone incrementally.
2. Request an upstream license and maintain a documented fork.
3. Preserve the clone as an audit reference and independently rewrite the product.

## Decision

Choose an independent rewrite. Start with governance, context, hooks, ADRs, validation, and Git history before application code.

## Implementation

Phase 0 creates:

- A compact authoritative project context
- Kiro steering and a local orchestrator configuration
- Sanitized, size-bounded lifecycle event logging
- Approval-gated shell/write tools with defense-in-depth Git and write-tool guards
- Standard-library hook and validator tests
- A dependency-free governance validator
- Product, provenance, architecture, and workflow records
- A minimal CI workflow with immutable action references

The hooks are not a process sandbox. A shell can express writes in ways no command classifier can safely enumerate. Shell and write therefore remain outside `allowedTools`; token-aware checks catch common dangerous Git forms and the dedicated write tool is confined to the repository.

## Privacy decision

Hook logs contain timestamps, one-way session fingerprints, allow-listed event metadata, sanitized tool names, branch category, commit, dirty state, and Git status only. Raw session IDs, raw branch names, prompt bodies, tool inputs, tool outputs, secrets, and user data are excluded. Invalid or legacy-schema logs are deleted before append, and every new record is validated before persistence. Logs rotate at 1 MB, use owner-only mode where supported, remain local, and are ignored by Git.

## Review findings and response

Independent review initially returned `NEEDS_CHANGES`. It found overstated guard guarantees, weak CI validation, fail-open events, unsafe legacy logs, mutable action references, branch-dependent tests, missing Git shorthand cases, and false-positive YAML gate detection. Each concrete finding was fixed and tested rather than waived. The final blocker-only review returned `PRECOMMIT_APPROVED`.

## Evidence

Local commits:

- `e1391acda89e8294203ed5fec2fce5e42b86a2c8` — `docs: define incident compiler scope and provenance`
- `c6fbf567344c12fc95ad359e695eb90633019f61` — `chore: add Kiro governance and validation gates`

Executed on Windows against committed `HEAD` `c6fbf567344c12fc95ad359e695eb90633019f61`:

- `git show --check --oneline --format=fuller HEAD` — passed
- `python -m py_compile scripts/validate_project.py .kiro/hooks/project_hook.py tests/test_project_hook.py tests/test_validate_project.py` — passed
- `python -m unittest discover -s tests -p "test_*.py" -v` — 16 tests passed
- `python scripts/validate_project.py` — passed in full mode
- `python scripts/validate_project.py --quick` — passed
- `kiro-cli agent validate --path .kiro/agents/incident-orchestrator.json` — exit code 0
- The live legacy log was scrubbed; its replacement passed the privacy schema check and remained ignored by Git
- `actions/checkout` and `actions/setup-python` were resolved through GitHub and pinned to full commit SHAs

## Limitations

Governance does not guarantee correctness or eliminate hallucination. The hook classifier reduces mistakes but does not sandbox a shell. Kiro's validator is a local gate rather than a GitHub Actions dependency. Hosted CI was not run because the repository has no remote, and no public license has been chosen. Aswani will manually push when ready.

## Next question

What is the smallest domain contract and deterministic RCA baseline that can be evaluated before adding APIs, databases, or Gemini?
