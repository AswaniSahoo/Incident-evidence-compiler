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

## Ways of working (industry-standard practice)

- Default to widely-accepted, mainstream engineering practice: design before non-trivial code, apply dependency inversion with infrastructure behind ports and adapters, and drive changes from tests of observable behavior.
- Ship small, vertically-sliced increments; keep every increment behind the full green gate and require an independent review before acceptance.
- Prefer incremental, backward-compatible upgrades: additive schema and API changes with forward-only versioned migrations; do not break an existing contract or the hermetic gate without a recorded ADR.
- Record significant architecture, schema, dependency, and security choices as ADRs; keep CI hermetic and deterministic, exercising real infrastructure only through opt-in integration tests.
- Configure through the environment and never commit secrets; expose typed errors at boundaries and add observability as behavior grows.
