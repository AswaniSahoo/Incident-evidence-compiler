# MASTER-PLAN — 2-Week Public Sprint to v1 (2026-07-17 → ~Jul 30)

> Decision context: NK Securities OA in ~2 weeks; Aswani allocates 4h/day here + 3h/day DSA (protected) + 1.5h krkn-ai/Jacob (LFX Jul 30 deadline, protected). Scope cuts recorded in ADR 0007. Owner: Aswani. Supervisor risk note at bottom — read it once, then execute.
> Budget: 14 days × 4h ≈ **56 focused hours**. The original design assumed 4 full weeks. This plan fits 56h ONLY because of the cuts below. Re-adding a cut item = losing a release gate. Don't.

## Current state (verified 2026-07-17)

Phases 0–3 COMPLETE (see devlogs): stdlib-only domain — metric evidence ledger (content-bound IDs), deterministic ranked-suspicion baseline with typed abstention, bounded RCAEval RE2 adapter (pinned 1.2.0 @ bc49dbd), change-event ledger + tri-state temporal co-occurrence verifier, canonical leakage-safe serialization, full gate (unittest/ruff/mypy/validate) green. NOT yet: any I/O framework, DB, LLM, API, metrics endpoint, real dataset on disk, license, remote.

## v1 definition (what "8+" means HERE — release gates)

- [ ] Public repo (license decided, ADR'd) with daily-commit history
- [ ] Async FastAPI control plane: POST /investigations → 202 + id · GET status · GET report; bearer-token auth with tenant scoping on every query
- [ ] PostgreSQL as source of truth (investigations, jobs, evidence, reports, audit); worker claims jobs via `SELECT … FOR UPDATE SKIP LOCKED`; idempotent creation
- [ ] Gemini via one async `LLMClient` protocol (`google-genai`) + deterministic `FakeLLMClient`; CI never needs credentials
- [ ] Restricted-hypothesis pipeline end-to-end: evidence ledger → Gemini proposes predicates → deterministic verifier → SUPPORTED/REFUTED/UNKNOWN report with evidence IDs
- [ ] Evaluation on real RCAEval RE2-OB (dev split) + ONE sealed RE2-TT run: Top-1/Top-3 root-cause accuracy, MRR, abstention rate, zero invalid evidence IDs — results committed as JSON artifacts
- [ ] Leakage sanitation tests green (labels/fault metadata provably absent from model context)
- [ ] Observability: OTel spans per stage + Prometheus `/metrics` (request count, stage p50/p95, provider timeout rate, token + est. cost counters)
- [ ] Stalled-model test: N stalled fake-LLM jobs do not block health endpoint
- [ ] CI gates: unittest + ruff + format + mypy + compileall + docker build
- [ ] README that claims exactly what artifacts prove; LIMITATIONS section; 2–3 min recorded demo
- [ ] 2 build-in-public posts (kickoff + results)

## CUT from v1 (ADR 0007 — the price of 56h; each is v2 backlog, not failure)

1. **Runbook RAG corpus + retrieval** — biggest cut. Retrieval novelty already lives in climate-risk-agent; the predicate-verifier pipeline is THIS project's novelty. Verifier consumes telemetry evidence only.
2. **Redis admission control** — Postgres-only concurrency for v1.
3. **Grafana dashboard** — Prometheus text endpoint + one screenshot suffices.
4. **OIDC/RBAC depth** — static bearer tokens + tenant_id scoping (row-level filtering), not a full identity system.
5. **Calibrated abstention with risk–coverage curve** — keep the existing typed abstention; calibration = v2 (needs time the sprint doesn't have; do NOT publish an uncalibrated curve).
6. **SSE streaming, DELETE endpoint, astronomy-shop demo, RE2-SS** — out.

## Day map (each day = slice + gate + push; falls behind → apply cut order, never skip gates)

| Day | Slice | Done-check |
|---|---|---|
| 1 (Jul 17) | **Decisions + publish**: license ADR (recommend Apache-2.0), GitHub remote, push phases 0–3 history, README "current state" truth pass, kickoff post. Download RE2-OB (1.19 GB) overnight. | repo public, CI green on GitHub |
| 2–3 | **Phase 4 — persistence boundary**: schema (investigations/jobs/attempts/evidence/reports/audit), repository protocols + in-memory fakes, psycopg async driver, migrations script, SKIP LOCKED job claim + tests (incl. two-worker race test via two connections) | gate + docker-compose postgres up, tests green both fake & real |
| 4 | **Phase 5a — provider boundary**: async `LLMClient` protocol, `FakeLLMClient`, restricted-hypothesis JSON schema + parser (reject unknown predicate types/entities) | hypothesis fuzz tests green |
| 5 | **Phase 5b — GeminiLLMClient** (`google-genai`): deadline, retry-once, token/cost capture, malformed-output typed failure | live smoke behind env flag; CI uses fake |
| 6–7 | **Phase 6 — control plane + worker**: async FastAPI app, auth middleware, POST 202/idempotency-key, GET status/report, worker loop (claim → build ledger → LLM → verify → persist), cancellation + deadlines | E2E test: POST→poll→report with fake LLM; stalled-model health test |
| 8 | **Phase 7a — real-data integration**: RE2-OB through adapter → ledgers in Postgres, sanitation tests on real paths | leakage tests green on real data |
| 9–10 | **Phase 7b — dev evaluation**: run baseline-only vs baseline+Gemini on OB dev split, metrics JSON (Top-1/3, MRR, abstention, invalid-ID count), fix worst failure class only | committed results artifact |
| 11 | **Phase 8 — observability**: OTel spans, Prometheus counters/histograms, stage latencies, token/cost metrics | /metrics scrape shows real numbers during eval rerun |
| 12 | **CI hardening + docs**: docker build gate, README architecture + eval tables, LIMITATIONS, PROJECT_CONTEXT final | full gate green from clean checkout |
| 13 | **Freeze + sealed run**: freeze prompt/model/thresholds manifest → single RE2-TT run → publish results (whatever they are) | sealed results committed, README updated honestly |
| 14 | **Buffer + demo + post 2 + resume bullets** (numbers linked to artifacts) | 2–3 min recording done |

## Slippage cut order (apply top-down, one per slipped day)
1. Day-11 OTel spans → Prometheus-only. 2. Day-9/10 becomes baseline-vs-Gemini on HALF the OB split. 3. Docker gate → local docker only. 4. Demo video → GIF. **Never cut:** tests, leakage sanitation, sealed-TT protocol, README truthfulness.

## Resume bullets (template — fill ONLY from committed artifacts)
- Built a multi-tenant async incident-investigation service (FastAPI, PostgreSQL SKIP-LOCKED workers, Gemini) that compiles telemetry into a content-addressed evidence ledger and verifies LLM-proposed hypotheses deterministically as SUPPORTED/REFUTED/UNKNOWN.
- Evaluated on [N] held-out RCAEval incidents: [X]% Top-1 / [Y]% Top-3 root-cause accuracy, MRR [Z], zero invalid evidence citations; label-leakage prevented by failing sanitation tests.
- Instrumented stage-level OpenTelemetry/Prometheus (p50/p95 per stage, token + cost per investigation); [N] stalled-model requests leave health endpoint responsive.

## Supervisor risk note (read once)
Honest odds this fully lands by Day 14: ~60%. The two schedule bombs: real-RCAEval preprocessing (Day 8 — everyone underestimates it; that's why download starts Day 1) and async worker correctness (Days 6–7). The cut order exists so slippage degrades scope, not quality. Hard rule: **if a DSA mock score drops below your baseline during week 2, DSA takes hours back from this plan the same day — OA failure makes both flagships worthless for NK.** LFX (krkn-ai, Jul 30) and Jacob's letter stay untouchable.
