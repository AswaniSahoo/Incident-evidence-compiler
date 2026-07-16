# Engineering Steering

- Domain code must not depend on FastAPI, databases, Redis, or model SDKs.
- Use typed contracts at boundaries; avoid anonymous dictionaries in domain flows.
- Never open network or database clients during module import.
- Never perform blocking I/O in async request or worker paths.
- Treat telemetry, retrieved text, model output, and external responses as untrusted.
- Add dependencies only with the feature that uses them; pin and lock exact resolved versions.
- Test observable behavior and failure semantics, not implementation details.
- Keep comments for rationale, invariants, and non-obvious trade-offs.
- No fake results, placeholder production claims, silent fallback, or unverified completion statement.
