# ADR 0012: Async LLM provider boundary (Phase 5)

- Status: Accepted
- Date: 2026-07-17
- Decision owners: Aswani and the project orchestrator

## Context

The product accepts restricted hypotheses from Gemini and verifies them deterministically;
the model is never trusted to access data or assert causes (product steering, ADR 0002).
Phase 5 introduces the single asynchronous provider boundary through which the model is
reached, while keeping domain code framework-independent and the CI gate hermetic (no
credentials or network in tests), per the engineering steering.

Phase 4 established the pattern for a runtime dependency behind a phase-aware validator
(psycopg, ADR 0011). Phase 5 adds the second runtime dependency, `google-genai`, under the
same governance.

## Decision

A new top-level package `src/incident_evidence_compiler/llm/`, delivered in two slices.

### Slice 5a, contracts, fake, and untrusted parser (standard library only)

- `client.py`: an async `LLMClient` `Protocol` with `propose_metric_hypotheses`, plus frozen
  typed records, `HypothesisRequest` (tenant, run, and the frozen allow-list of signal keys
  a proposal may reference) and `LLMProposal` (opaque `raw_json` plus optional model/token
  metadata). Callers depend on the protocol, never a concrete backend.
- `errors.py`: an `LLMError` hierarchy mirroring the domain convention, a stable `code`
  class variable and no free-form message, so nothing from the model leaks across the
  boundary. Input-validation failures are `LLMValidationError` subclasses
  (`MalformedProposalError`, `EmptyProposalError`, `ProposalSchemaError`,
  `UnauthorizedEntityError`, `TooManyPredicatesError`, `ProposalTooLargeError`); operational
  provider failures are `LLMError` subclasses (`ProviderTimeoutError`,
  `ProviderUnavailableError`, `ProviderResponseError`).
- `parsing.py`: `parse_metric_hypothesis(raw, *, allowed_signals)` treats `raw` as fully
  untrusted, enforces an input-size ceiling before parsing, rejects empty text, parses JSON
  defensively, requires a JSON object, delegates deep structural validation to the domain's
  `validate_hypothesis_document`, and then enforces the caller's signal allow-list and the
  domain predicate budget. Every rejection raises a message-free error with its cause
  suppressed (`from None`), so no model-derived text survives anywhere in the exception.
- `fake.py`: `FakeLLMClient` replays scripted proposals deterministically (including
  malformed ones) for hermetic tests.

### Slice 5b, Gemini adapter (adds `google-genai`)

- `gemini.py`: `GeminiLLMClient` implements `LLMClient` over a narrow injected port
  (`_AsyncModels`), so retry, timeout, token capture, and malformed-response handling are
  unit-testable without a network; the `google-genai` SDK coupling is confined to one adapter
  with a single `Any` seam and is imported lazily only in `from_api_key`. Each attempt is
  bounded by a deadline; a transient failure is retried once; a timeout, exhausted retry, or
  malformed/empty response each raise a stable provider error.
- `google-genai==2.12.1` is added as the second runtime dependency, pinned exactly in
  `pyproject.toml` and `uv.lock`. The project validator's phase-aware dependency allowance is
  extended to Phase 5; Phases 1–3 still require an empty runtime dependency set and Phase 4
  allows only psycopg.

### Testing strategy

The hermetic gate exercises the protocol, the fake, the untrusted parser (fuzz/failure
cases), and the Gemini client's retry/timeout/token/malformed behavior via injected stubs,
all without network or credentials. A single live smoke test is gated on `GEMINI_API_KEY`
(`skipUnless`) and is skipped in CI.

## Consequences

### Positive

- The worker/control plane (later phases) depend only on `LLMClient` and can run entirely on
  the deterministic fake; the real Gemini path is swapped in by configuration.
- Model output is contained: untrusted JSON only becomes domain types through one audited
  parser that reuses the domain validators and enforces the run's entity allow-list.
- Provider failure modes are typed and leakage-safe; CI never needs a key.

### Cost

- `google-genai` is the second runtime dependency; it pulls a transitive tree (httpx,
  pydantic, etc.) now present in `uv.lock`.
- The live Gemini call is not exercised in CI by design; its correctness rests on the injected
  stub tests plus the opt-in smoke test.

## Rejected alternatives

- **Depend on `google-genai` types directly in the client**: would spread SDK coupling and
  weaken hermetic testability. Rejected in favor of the injected `_AsyncModels` port.
- **Parse model output into ad-hoc dictionaries**: would bypass the domain contracts and the
  entity allow-list. Rejected; the parser returns validated domain hypothesis types only.
- **Make the LLM package optional / vendor-neutral abstraction layer now**: premature; one
  provider is in v1 scope (accepted decisions). A second provider can reuse the same protocol.

## Verification (2026-07-17)

Implemented on `phase/05-llm-provider`. Hermetic locked gate green: ruff, `ruff format
--check`, and mypy clean; the LLM tests pass (parser fuzz/failure cases and the Gemini
client's retry/timeout/token/malformed behavior via stubs) with one live smoke test skipped
without `GEMINI_API_KEY`; the project validator passes (full) under Phase 5; `uv sync
--locked` resolves. Honest scope: a live Gemini API call was not made in the implementation
environment (no key); that path is covered by the opt-in smoke test only.
