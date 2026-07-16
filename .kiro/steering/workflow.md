# Workflow Steering

- Begin from `PROJECT_CONTEXT.md`; verify stale claims against code, tests, Git, or ADRs.
- Work in phase order and one vertical slice at a time.
- Major product, security, dependency, schema, and infrastructure decisions require Aswani's approval.
- Delegate implementation and independent review to separate agents when practical.
- Run targeted tests after changes and the full phase gate before a phase commit.
- Update context and the phase devlog when decisions, verified results, or next actions change.
- Use phase branches and conventional commits; never push, amend, force, or destructively reset without explicit approval.
- Shell and write are not auto-allowed. Hook guards reduce accidental misuse but are not a process sandbox; approved publication uses dedicated provider tooling or a user-run Git command because shell pushes remain disabled.
- Keep local hook logs sanitized; never store prompt bodies, tool inputs, tool outputs, secrets, or user data.
