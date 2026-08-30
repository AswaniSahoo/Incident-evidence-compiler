# Devlog 0017 — A divergent default, and the test that stops it recurring

Status: fixed on `main` in commit `fca8757` (2026-08-23). Recorded here after the fact, because the
incident was worth a devlog of its own and originally had only a commit and a test docstring to show
for it.

## 1. Symptom

The opt-in live Gemini smoke test started failing with an HTTP 404 from Vertex AI. Everything else
kept working: the containerized demo, the evaluation harness, and every production code path that
reaches the same provider.

A failure that appears in exactly one place is a failure with a discriminating clue attached. The
useful question was not "why is the call failing" but "what does that one caller do differently".

## 2. Elimination

Three candidate causes, each ruled out by an observation rather than by argument.

- **Credentials.** Ruled out: the same Application Default Credentials authenticated every other
  call in the same session, including a successful live run.
- **Project or region.** Ruled out: both are passed identically on the failing and the working
  paths, and a 404 from a reachable endpoint is not how a wrong project or an unset region fails.
- **The model name.** Not ruled out, and the only asymmetry left. Every production caller passes
  `model` explicitly, because `AppConfig` resolves it from `IEC_GEMINI_MODEL` and threads it through.
  The smoke test constructs the client with no model argument and therefore falls through to the
  parameter default.

So the defect was not on the call path at all. It was in the default value, which no production
caller ever reads.

## 3. Cause

Two modules held the same constant and had drifted apart:

- `src/incident_evidence_compiler/llm/gemini.py` still defined `_DEFAULT_MODEL = "gemini-2.0-flash"`,
  used as the default for three constructors.
- `src/incident_evidence_compiler/runtime/config.py` had already moved to
  `_DEFAULT_MODEL = "gemini-2.5-flash"`.

The Vertex endpoint no longer served `gemini-2.0-flash`, which produced the 404.

The drift was invisible precisely because it was well encapsulated. Config is the only thing that
reads its own default, and every real caller overrides the client's. A stale default is a value that
is wrong and unreachable at the same time, until one caller takes the unreachable path.

## 4. Fix, and the guard

The fix is one line: point the client default at `gemini-2.5-flash`.

Shipping only that would have left the same class of defect available, since nothing prevents the two
constants diverging again next time either moves. The same commit therefore adds a contract test:

```python
# tests/test_llm_gemini.py:153
def test_client_default_matches_the_configured_default(self) -> None:
    self.assertEqual(gemini._DEFAULT_MODEL, config._DEFAULT_MODEL)
```

`git show --stat fca8757` shows one commit touching
`src/incident_evidence_compiler/llm/gemini.py` (2 lines) and `tests/test_llm_gemini.py`
(15 lines added). Both constants read `gemini-2.5-flash` today, at `gemini.py:22` and
`config.py:16`, and the suite fails if they stop agreeing.

## 5. Why it is recorded

Three reasons, none of them the bug itself, which was trivial.

The **diagnosis** is the part worth keeping: the contradiction between a failing test and a working
production path was the whole clue, and eliminating candidates by observation rather than by
plausibility is what made it a five-minute problem instead of a provider-support ticket.

The **shape** recurs. A default that no caller reads is a value with no test pressure on it. Any
constant duplicated across a boundary has this property, and the cheap defence is a contract test
asserting the two agree, not vigilance.

The **detection gap** is real and remains. This was found by an opt-in test that the hermetic gate
skips, because it needs credentials and a network. Had nobody run the live path by hand, the stale
default would have sat there indefinitely. That is an accepted trade: the gate stays hermetic
(ADR 0012), and the cost is that provider-facing drift is only caught when someone opts in.

## 6. Related

The same instinct, applied to a test rather than to production code, produced devlog 0016: a fuzz
harness that passed on its first run, distrusted, and then measured, revealing that the allow-list
branch had zero coverage across 1,500 generated cases. A green test proves nothing until you measure
what it exercised, and a passing default proves nothing until someone reads it.
