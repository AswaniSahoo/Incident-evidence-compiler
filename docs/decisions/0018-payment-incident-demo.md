# 0018 — A payment-infrastructure incident demo (honest reskin, no domain change)

- Status: accepted
- Date: 2026-08-23 (accepted 2026-08-23, implemented on `feat/payment-incident-demo`)
- Deciders: Aswani
- Supersedes: none
- Related: 0002 (model proposes, deterministic system decides), 0016 (runnable entrypoint),
  0017 (Prometheus ingestion + the bundled synthetic demo this reskins)

## Context

IEC is being shown for an evaluated, hire-me setting whose bar is a working, honestly-measured
system in a domain the evaluator recognises: payment infrastructure. The evaluator's own rubric
rewards "the right tool in the right place, **and where you chose not to use one**" — which is
precisely IEC's thesis (a model proposes restricted hypotheses; a deterministic verifier decides;
`UNKNOWN` is first-class).

The gap is only in *presentation*. ADR 0017's demo exports abstract microservice signals
(`cart`, `catalogue`, `checkout`, `payment`) with metrics named `demo_*`. That proves the ingestion
path but tells no story a payments reviewer connects with. Nothing in the architecture needs to
change to tell that story — the same evidence ledger → baseline → verifier pipeline works on any
signal names.

Two hard constraints frame the decision:

- **The frozen domain must not move to sell a narrative.** The reskin is confined to the demo
  artifacts; ports, verifier, config code, and the hermetic gate stay byte-for-byte as they are.
- **No fake production or fake vendor claim (AGENTS.md).** The data stays synthetic and labelled;
  we do not wire a real Razorpay/payment API to imply an integration that isn't there.

## Decision

Reskin the ADR 0017 demo into a **payment-infrastructure incident** — a bank-router deploy that
degrades routing — told entirely through renamed synthetic signals and documentation. No domain,
port, verifier, or config-code change.

1. **Payment-infrastructure signal vocabulary (demo layer only).** The synthetic exporter emits two
   gauges per component — `payment_error_ratio{component=…}` and `payment_latency_seconds{component=…}`
   — over four components: `bank_router` (the freshly-deployed, degrading one), `checkout`,
   `upi_switch`, and `ledger_db`. Same two-metric-per-component shape as today, so the
   series→signal mapper and baseline arithmetic are unchanged; only the strings differ. (Names are a
   proposal — Aswani owns the final vocabulary.)

2. **One faulty component, one flat decoy — the contrast is earned, not scripted.** `bank_router`'s
   error ratio and latency climb after the injection instant (the "bank-router-service deploy");
   the other three stay flat. `ledger_db` is the deliberate **decoy**: a genuinely healthy
   database-shaped signal. When the model's hypothesis names `bank_router`, the verifier returns
   `supported` with cited evidence; when it reaches for `ledger_db` (a plausible-sounding culprit),
   the verifier returns `unknown` / `weak_evidence`. Both verdicts are produced by the real verifier
   against real (synthetic) ingested data — the refusal is demonstrated, not staged.

3. **Honesty guardrails carry over verbatim.** The exporter keeps its "this file invents numbers"
   docstring and `DEMO DATA` metric HELP text. The model sees only signal *names*, never values, so
   a correct pick over symmetric names is a guess; the run reports whatever the model returns, luck
   is labelled as luck, and a result is never re-rolled for a prettier verdict. The verifier is the
   source of truth — that is the whole point being demonstrated.

4. **A README use-case section, honestly framed.** A short "As a payment-infrastructure incident
   investigator" section maps IEC's guarantees to the payments bar ("every money action
   explainable, bounded and gated") in the evaluator's own words, and states plainly that the demo
   is synthetic and IEC stops at the evidence-verified diagnosis — it does not act.

5. **Verified by the live demo run, not the hermetic gate.** Like ADR 0017's demo, the reskin is a
   manual, Docker-based run (`docker compose --profile demo up`), not a CI addition. Any renamed
   unit assertions in the demo path keep passing; `EXPECTED_CI_RUNS_BY_PHASE` and the locked gate are
   unchanged.

## Consequences

- IEC reads as a payment-infrastructure incident investigator in a five-minute demo, with zero risk
  to the core: the diff is exporter strings, `IEC_PROM_QUERIES`, the driver, the README, and this
  ADR. The 336-test gate is untouched.
- The `supported` + `unknown` contrast — the thesis in action — is visible in a single report, from
  the real verifier, on labelled synthetic data.
- No new dependency, no domain change, no vendor integration; `pyproject.toml` / `uv.lock`
  unchanged.
- The demo remains explicitly synthetic; no claim is made about accuracy on production payment
  telemetry.

## Alternatives considered

- **Wire Razorpay test-mode APIs for a "real integration" optic** — rejected. IEC ingests
  *telemetry* (Prometheus metrics), not *transactions*; a payments SDK produces orders/payments that
  never feed the evidence ledger, so the integration would be a logo on a slide, not a data path.
  It also adds a dependency and credential handling for zero investigative signal. Choosing not to
  build this is itself the "where you chose not to use a tool" judgment the setting rewards.
- **Enter Track 03 (AI Revenue Recovery) instead of Open Track** — rejected. Its bar demands
  *measured money recovered* via a recovery-execution loop; IEC deliberately stops at the
  evidence-verified diagnosis and refuses autonomous action. Forcing a recovery step would violate
  IEC's own philosophy. Open Track lets IEC stand as the trustworthy diagnosis layer such a loop
  would depend on.
- **Fork the domain to model payment success-rate / bank response codes richly** — deferred. A
  faithful payment-telemetry model (success-rate decrease, per-bank timeout series, deploy/change
  events as first-class evidence) is real product scope, not a demo, and would move the frozen
  domain. The renamed two-metric shape tells the story honestly without that cost.
