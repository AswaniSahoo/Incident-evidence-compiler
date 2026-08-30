# Devlog 0013, A payment-infrastructure incident demo (ADR 0018)

Status: implemented on branch `feat/payment-incident-demo` (ADR 0018, **accepted**). Demo-layer
reskin only, no domain, port, verifier, or config-code change; the hermetic gate is untouched.

## 1. Problem

ADR 0017 proved the ingestion path against a real Prometheus, but its demo spoke in abstract
microservice signals (`cart`, `catalogue`, `checkout`, `payment`, metrics `demo_*`). For an
evaluated, payments-shaped setting that tells no story a reviewer connects with. The gap was
presentation, not architecture: the same evidence ledger → baseline → verifier pipeline works on
any signal names.

## 2. First principle

Don't move the frozen domain to sell a narrative, and don't fake a vendor integration. Reskin only
the demo artifacts; keep the data synthetic and labelled. The strongest, most honest thing to show
is the system's *judgment*, the model proposing, the verifier refusing what the data doesn't
support, so the scenario just needs a faulty component and a plausible decoy.

## 3. Decision

Reskin the ADR 0017 demo into a **bank-router deploy incident** told through renamed synthetic
signals: `payment_latency_seconds` / `payment_error_ratio` over `bank_router` (faulty), `checkout`,
`upi_switch`, and `ledger_db` (a healthy database-shaped decoy). Files touched: the exporter,
`IEC_PROM_QUERIES` in compose, the driver's incident label, the README, this devlog, ADR 0018.
Explicitly rejected: wiring a real Razorpay API (IEC ingests telemetry, not transactions, the SDK
would never feed the ledger; see ADR 0018 alternatives).

## 4. The two runs (2026-08-23)

Both ran against the reskinned `demo` profile: a real `prom/prometheus:v3.6.0` scraping the
synthetic exporter over a four-minute window straddling the injection.

**Vertex (the headline).** `IEC_LLM_PROVIDER=vertex`, host-process compiler against the
containerized Prometheus so ADC sufficed with no credential mounted into any image. The active
gcloud project was `climate-risk-agent`, so isolation was explicit: ambient `GOOGLE_CLOUD_PROJECT` /
`GOOGLE_CLOUD_LOCATION` / `GOOGLE_GENAI_USE_VERTEXAI` were stripped from the child, and
`IEC_GEMINI_PROJECT` **and** `GOOGLE_CLOUD_QUOTA_PROJECT` were pinned to `iec-live-demo`. The call
landed where intended:
`POST …/projects/iec-live-demo/locations/us-central1/…/gemini-2.5-flash:generateContent → 200`.

Gemini proposed hypothesis `payment_transaction_degradation` over **four** predicates. The verifier
resolved each against the ingested ledger:

| Predicate | Verdict | Evidence |
|---|---|---|
| `bank_router_latency_increase` | **`supported`** | `sha256:758e1134…` |
| `checkout_error_increase` | `unknown` (`weak_evidence`) | none |
| `ledger_db_error_increase` | `unknown` (`weak_evidence`, observed `decrease`) | none, the decoy |
| `upi_switch_latency_increase` | `unknown` (`weak_evidence`, observed `decrease`) | none |

`iec_investigation_verdicts_total{verdict="supported"} 1`; one succeeded job; no traceback. **One
verified-true, three guesses withheld, zero false assertions.** The model over-reached four ways,
including reaching for the `ledger_db` decoy, and the verifier endorsed only the single claim the
data supported. This is a stronger demonstration than ADR 0017's checkout run: the refusal is shown
three times over, on real ingested (synthetic) data, from the real model.

**Fake client (no API).** `IEC_LLM_PROVIDER=fake` names the lexicographically-first ingested signal,
which under the new vocabulary is `payment_error_ratio{component="bank_router"}`, the faulty one.
It returned `supported` citing `sha256:8a99b796…`. That is alphabetical luck, not intelligence
(labelled as such), but it proves the ingestion path carries real content-addressed evidence end to
end with no provider at all.

## 5. Reproducible evidence

```bash
docker compose --profile demo up -d --build
uv run --locked python scripts/demo_live_investigation.py   # fake client, no API
docker compose --profile demo down -v
```

For the Vertex run: stop the compose `compiler`, run `python -m incident_evidence_compiler` as a
host process with the isolated env above (`IEC_LLM_PROVIDER=vertex`,
`IEC_GEMINI_PROJECT=iec-live-demo`, `IEC_PROM_URL=http://localhost:9090`,
`IEC_PROM_QUERIES="payment_latency_seconds ; payment_error_ratio"`), then run the same driver.

The hermetic gate is unchanged and green: `ruff check` clean, `ruff format --check` clean, strict
`mypy`, the full `unittest` suite, and `python scripts/validate_project.py`. `pyproject.toml` and
`uv.lock` are byte-identical to `main`, no new dependency, exactly as ADR 0018 requires.

## 6. Honesty reading

Gemini sees only signal *names*, never values, and the components are named symmetrically, so a
correct pick is a guess toward plausible-sounding culprits, here, four guesses of which one
happened to be right. The verifier, not the model, is the source of truth: it grounded the one true
claim in a content-addressed evidence ID and withheld the other three, the decoy included. The
numbers are invented and the exporter says so; this proves the ingestion and the gating, not
diagnostic accuracy on production payment telemetry.

## 7. Limitations (unchanged from ADR 0017, restated for the payment framing)

- Synthetic data. The demo proves the path, not accuracy on real payment telemetry.
- The baseline's ranking still isn't exposed by the HTTP API (the next slice, baseline-ranking
  endpoint, addresses exactly this).
- Selectors are process-wide, not per tenant.

## 8. Next question

Should the report expose the baseline ranking so the demo doesn't need a driver to narrate which
signal moved, the one piece of the story the API still can't show on its own?
