# 0019: pre-submission adversarial review, five fixes, and what was left open

Date: 2026-08-31 (fixes), 2026-09-02 (this entry)

## What ran

An adversarial review pass over `src/` and `tests/`, AI-assisted under the AGENTS.md contract, with
every finding verified against the code before it was accepted and every fix landed test-first.
The verifier itself (`domain/verifier.py`) came out with no defects: the inclusive threshold is
tested at exact equality, empty compositions and duplicate signal keys are unreachable by
construction, timezone handling is aware end to end, and evidence hashing is canonical. The
defects were all at the edges, which is where they usually are.

## Fixed, with the test that pins each one

1. **A poison job could be reclaimed forever** (`11e1612`). The claim's `attempt_count` increment
   shared one transaction with the whole pipeline, so any exception not mapped to a typed failure
   rolled the counter back along with the work: the job returned to `queued` unchanged and
   `max_attempts` could never fire. `run_once` now fails such a job closed with the stable code
   `internal_error`. Test: `test_poison_job_fails_closed_instead_of_being_reclaimed_forever`.
2. **Fault labels reached the prompt in demo mode** (`d49e511`). With `IEC_TELEMETRY=rcaeval` the
   served `incident_id` was the case directory path, which RE2 names `<service>_<fault>`, and the
   worker embeds `incident_id` verbatim in the model prompt. Cases are now keyed by an opaque
   sha256 digest; `locator_for()` keeps them findable by an operator. The evaluation harness was
   never affected, it keys cases by random UUID, so no published number changes. Tests assert the
   label is not recoverable from the id.
3. **A blank `Idempotency-Key` returned 500** (`ab9b322`). The persistence record rejected it with a
   `PersistenceValidationError` that the route did not catch. Now 422 `invalid_idempotency_key`.
   The same commit caps `incident_id`, `run_id`, and the key at 200 characters, because all three
   are interpolated into every model call and an uncapped value is a cost lever for any tenant.
4. **Bearer tokens were compared by dict lookup** (`e866da4`). Now `hmac.compare_digest` over the
   registry.
5. **Driver detail could reach logs** (`563217e`). Four `raise IdempotencyConflictError from exc`
   sites kept the psycopg `UniqueViolation` as `__cause__`, so `logger.exception` could print
   constraint DETAIL. Now `from None`.

Gate after the fixes: 346 tests OK (10 skipped without infrastructure), ruff, `ruff format`,
mypy strict over 90 files, `validate_project.py` full pass.

## Found, disclosed, and deliberately not fixed before submission

Each of these is a real finding. Each would change runtime behaviour days before a deadline for
no benefit a reader can see, so they are recorded here and in the README's "What it doesn't do
(yet)" rather than patched in a hurry.

- **The in-memory store serializes the control plane behind the worker.** `InMemoryUnitOfWork`
  holds one factory-wide lock for a whole job, including the model call, so with
  `IEC_PERSISTENCE=memory` the data routes wait for up to the provider deadline. `/health` and
  `/metrics` do not. PostgreSQL has no such coupling. The right fix is narrowing the unit-of-work
  scope around the model call, which touches the transaction design and needs its own ADR.
- **The lease-expiry claim branch is unreachable on PostgreSQL** for the same structural reason:
  `claimed` is never committed on its own, so a crashed worker's job is recovered by rollback,
  not by lease expiry. Correct today, but the lease machinery describes a two-transaction queue
  the worker does not yet implement.
- **Evidence rows are deduplicated by `(tenant, run, evidence_id)` but listed by investigation.**
  Two investigations over the same run share a ledger, and the second one's evidence listing can
  come back empty while its report still cites valid IDs. The in-memory fake reproduces it, so the
  test is cheap; the fix is a scoping decision.
- **The change-event ledger is implemented and tested but not wired.** Nothing constructs a
  `ChangeEventLedger` and `LedgerKind.CHANGE` is never written; deployment co-occurrence
  verification waits for an ingestion source.
- **The persisted evidence payload is not the hash preimage.** Serialization replays byte for
  byte from the same domain inputs, which is what the README claims; what a stored row cannot do
  on its own is re-derive its `evidence_id` without reassembling tenant, run, window, and policy
  from the neighbouring tables. Storing the full preimage is a migration-sized change.
- **Retries have no backoff** and the served baseline threshold (1.0) differs from the evaluated
  one (3.0). The threshold now has an environment override (see the follow-up below).

## 2026-09-02 follow-up: two additions aimed at "does it run"

Both were built test-first by agents under the AGENTS.md contract, with disjoint file sets, and
reviewed line by line before commit.

**`IEC_BASELINE_MIN_SCORE`.** The served worker defaulted to `minimum_score=1.0` while the
published evaluation ran `3.0`, and nothing could change it without editing code. `AppConfig`
now parses an optional finite float `>= 0`; when set, `build_components` passes
`dataclasses.replace(DEFAULT_BASELINE_POLICY, minimum_score=...)` to the worker. The default is
deliberately unchanged so the two published demo transcripts stay reproducible. Two behavioural
tests pin it through the API: without the variable the report's `baseline_ranking.policy.minimum_score`
is `(1.0).hex()`, with `3.0` it is `(3.0).hex()`. The `ConfigError` messages name the variable and
never the value.

**A hermetic one-command demo.** `scripts/demo_hermetic_investigation.py` starts the real
entrypoint (`python -m incident_evidence_compiler`) as a subprocess on a free loopback port with
the in-memory store, the labelled smoke client, and the committed synthetic RE2-OB fixture, then
drives one investigation over real HTTP and prints the verified report and the deterministic
baseline ranking. No Docker, no credentials, no network beyond loopback. The ranking formatter is
shared with the live driver (`scripts/_demo_common.py`), so both print alike, and the live driver
now shows the ranking the earlier transcripts could not. An end-to-end test runs the script as a
subprocess and asserts the banner, the verdict, and the ranking block.

**Cross-platform check.** Everything above was developed on Windows 11, and CI runs on Linux, so
the branch head was archived (`git archive HEAD`) and the whole gate was run inside WSL2 Ubuntu
24.04.4 LTS with uv 0.11.17 and a uv-managed CPython 3.12.13: `compileall` clean, 362 tests OK
(10 skipped without infrastructure) in 6.8 s, the hermetic subprocess test alone OK in 2.05 s,
`validate_project.py` full pass, and the demo printed the same verdict and ranking as on Windows.

**Review of the additions.** A code-review pass over the two additions returned eight verified
findings, all fixed before commit: the demo inherited ambient `IEC_*` variables from the
operator's shell (now stripped), its retry budget could outlast the end-to-end test's timeout and
orphan the server (now wall-clock deadlines well inside the timeout), non-409 answers were retried
into a timeout instead of reported (now fail fast with the stable error code), the test's ranking
assertion was satisfiable by the formatter's own fallback string (now asserts on lines the
fallback cannot produce), `PYTHONSAFEPATH=1` broke the `_demo_common` import (now explicit
`sys.path`), and two README bullets overclaimed what the prompt carries and what model text
survives (now stated exactly). A security review of the same diff found nothing at HIGH or
MEDIUM.
