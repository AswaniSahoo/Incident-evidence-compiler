# Devlog 0006 — Phase 5: async LLM provider boundary

Status: in progress on branch `phase/05-llm-provider` (not yet merged to `main`). Phase 5a
is committed; Phase 5b (Gemini + governance) is implemented and pending independent review.

## Goal

One asynchronous `LLMClient` boundary through which restricted metric-shift hypotheses are
proposed, with model output treated as untrusted and verified deterministically downstream
(ADR 0012). CI stays hermetic against a deterministic fake; the real Gemini path is opt-in.

## Slices

- Slice 5a (no dependency, committed): `llm` package — async `LLMClient` protocol, typed
  `HypothesisRequest`/`LLMProposal`, a leakage-safe `LLMError` hierarchy, `FakeLLMClient`, and
  `parse_metric_hypothesis` that treats model JSON as untrusted (size ceiling before parse,
  empty/'{}' checks, defensive `json.loads`, domain-validator reuse, predicate budget, and a
  signal allow-list), raising message-free errors with the cause suppressed.
- Slice 5b (adds `google-genai==2.12.1`): `GeminiLLMClient` over an injected `_AsyncModels`
  port with per-attempt deadline, retry-once, token capture, and typed
  timeout/unavailable/malformed failures; the SDK is imported lazily and confined to one
  adapter. The validator is made phase-aware for Phase 5; Phases 1–3 still require an empty
  runtime dependency set and Phase 4 allows only psycopg.

## Testing strategy

The hermetic gate covers the protocol, the fake, the untrusted parser (fuzz/failure cases),
and the Gemini client's retry/timeout/token/malformed handling via injected stubs — no
network or credentials. A single live smoke test is gated on `GEMINI_API_KEY` and skipped in
CI.

## Verification note

Hermetic gate green: ruff, `ruff format --check`, mypy clean; LLM tests pass with the live
Gemini smoke skipped; `validate_project.py` passes (full) under Phase 5; `uv sync --locked`
resolves. A live Gemini API call was not made in the implementation environment (no key); the
real path is exercised only by the opt-in smoke test when `GEMINI_API_KEY` is set. This is
stated honestly rather than claimed as verified.
