# Phase 0: Foundation Before Features

- Date: 2026-07-16
- Status: Ready for final independent re-review and commit

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
- Standard-library hook behavior tests
- A dependency-free governance validator
- Product, provenance, architecture, and workflow records
- A minimal CI workflow

The hooks are not a process sandbox. In particular, a shell can express writes in ways a command regex cannot safely classify. The shell and write tools therefore remain outside `allowedTools`; the hook catches known dangerous Git forms and confines the dedicated write tool to the repository.

## Privacy decision

Hook logs contain timestamps, one-way session fingerprints, sanitized hook/tool names, branch category, commit, dirty state, and Git status only. Raw session IDs, raw branch names, prompt bodies, tool inputs, tool outputs, secrets, and user data are excluded. Legacy-schema logs are deleted before a new event is appended. Logs rotate at 1 MB, use owner-only mode where the operating system supports it, remain local, and are ignored by Git.

## Review findings and response

The first independent review returned `NEEDS_CHANGES`. It correctly found that the original guard was bypassable while documentation overstated it, CI lacked behavior tests, malformed covered events failed open, and raw session/branch metadata could leak sensitive naming. The implementation and policy were changed rather than waiving those findings.

## Evidence

Executed locally on Windows from the new repository:

- `python -m py_compile scripts/validate_project.py .kiro/hooks/project_hook.py tests/test_project_hook.py tests/test_validate_project.py` — passed
- `python -m unittest discover -s tests -p "test_*.py" -v` — 16 tests passed
- `python scripts/validate_project.py` — passed in full mode
- `python scripts/validate_project.py --quick` — passed
- `kiro-cli agent validate --path .kiro/agents/incident-orchestrator.json` — exit code 0
- Manual hook smoke tests verified blocked push and out-of-workspace write events returned exit code 2
- The live legacy log was scrubbed; its replacement passed the privacy schema check and remained ignored by Git
- GitHub Actions references were resolved through GitHub and pinned to full commit SHAs

Final independent re-review and root-commit evidence remain pending.

## Limitations

Governance does not guarantee correctness or eliminate hallucination. Regex guards reduce mistakes but do not sandbox a shell. Kiro's own agent validator is part of the local phase gate but is not installed in the minimal GitHub Actions job; CI separately checks JSON structure and executes hook behavior tests.

## Next question

What is the smallest domain contract and deterministic RCA baseline that can be evaluated before adding APIs, databases, or Gemini?
