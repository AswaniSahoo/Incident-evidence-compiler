# RE2-TT sealed held-out run, protocol and log (Step 4)

Purpose: convert the development-set result (RE2-OB) into a single **held-out** number on the
sealed RE2-TT split, run exactly once against a frozen configuration. This is the last
credibility upgrade before the resume/README can claim a held-out accuracy.

Status: **RUN ONCE on 2026-07-19** at freeze commit `0a7854e`. RE2-TT stays sealed by default
(ADR 0009); this single authorized pass is the reported held-out result and will not be re-run.
Aggregate, label-free artifacts: `docs/evaluation/re2-tt-baseline.json`,
`docs/evaluation/re2-tt-gemini.json`.

## Hard rules (do not violate)

- Freeze first, run once. Do not tune anything against TT, and do not re-run it to chase a
  better number, the first run is the reported run.
- RE2-TT raw data is never committed and lives outside the repository root (ADR 0009).
- Only the aggregate, label-free metrics JSON is committed; per-case ground truth and source
  locators never leave the evaluation sidecar.
- Opening TT requires an explicit authorization (`authorize_sealed_split(confirmed=True,
  reason=...)`, `src/incident_evidence_compiler/evaluation/rcaeval/ids.py`). Unauthorized by
  default. This holds for the evaluation loader, `RcaevalAdapter`. The served demo source does
  not check it: `IEC_TELEMETRY=rcaeval` with `IEC_RE2_SPLIT=TT` opens TT with no permit
  (`src/incident_evidence_compiler/runtime/telemetry.py:54-55`), listed under Known gaps in
  `README.md`.

## Frozen configuration (locked before the run)

Taken verbatim from the accepted RE2-OB development run so the two are comparable:

| Parameter | Frozen value | Source |
|---|---|---|
| `minimum_points_per_window` | 2 | `docs/evaluation/re2-ob-*.json` |
| `minimum_score` | 3.0 | development run |
| `minimum_margin` | 0.0 | development run |
| `relative_scale_floor` | 0.0 | development run |
| `scale_floor_relative_fraction` | 0.05 | `ScaleFloorPolicy` default |
| `scale_floor_absolute_epsilon` | 1e-9 | `ScaleFloorPolicy` default |
| Gemini model | `gemini-2.5-flash` | development run |
| Prompt | `_build_prompt` in `llm/gemini.py` (unchanged) | frozen at run time |
| Arms | `baseline` (deterministic) and `gemini` (verifier-gated) | same two arms as OB |

Before running: record the exact `git rev-parse HEAD` here so the freeze is auditable.

- Freeze commit: `0a7854e6111705b68693de254b6369ca51c42ad0` (the `--sealed-confirm` seam slice;
  working tree clean; both arms run at this commit on 2026-07-19).

## Preconditions

1. RE2-TT downloaded, checksum-verified, and extracted **outside** the repo as a directory
   named `RE2-TT` (same guardrail as RE2-OB, ADR 0009).
2. Gemini access: Vertex AI ADC (`gcloud auth application-default login`) or a
   `GEMINI_API_KEY`.
3. A one-line sealed-authorization seam in `scripts/run_evaluation.py` (a `--sealed-confirm
   "<reason>"` flag that builds a `SealedSplitPermit` and passes it to `RcaevalAdapter.load`).
   The seam exists: it landed in freeze commit `0a7854e` (`scripts/run_evaluation.py:59-64`,
   `171-189`) with three tests (`tests/test_evaluation.py:311`, `328`, `336`). Without the flag
   the script refuses TT.

## Procedure (one pass, both arms)

```bash
# 0. Freeze: record HEAD above, confirm the config table matches the committed OB JSON.

# 1. Cheap pre-check on a handful of cases first (still counts as "opening" TT, do this only
#    once you intend the real run; it is here to catch a path/credential mistake, not to tune).
uv run --locked python scripts/run_evaluation.py \
    --root /path/to/RE2/RE2-TT --split TT --arm baseline --limit 5 --sealed-confirm "final held-out eval"

# 2. Full baseline arm (deterministic, no network).
uv run --locked python scripts/run_evaluation.py \
    --root /path/to/RE2/RE2-TT --split TT --arm baseline \
    --sealed-confirm "final held-out eval" \
    --out docs/evaluation/re2-tt-baseline.json

# 3. Full verifier-gated Gemini arm.
uv run --locked python scripts/run_evaluation.py \
    --root /path/to/RE2/RE2-TT --split TT --arm gemini \
    --provider vertex --project <gcp-project> --location us-central1 \
    --model gemini-2.5-flash --concurrency 4 \
    --sealed-confirm "final held-out eval" \
    --out docs/evaluation/re2-tt-gemini.json
```

## After the run

- Commit `docs/evaluation/re2-tt-*.json` (aggregate, label-free only).
- Update the README evaluation table with the held-out row **exactly as measured**, whatever
  the numbers are. A worse held-out number than dev is normal and is reported honestly.
- Only then fill the resume bullet's held-out placeholder.

## Results log

Overall metrics (an abstention counts as a miss, so accuracy reflects coverage). 90 cases,
0 skipped. The Invalid IDs column is 0 by construction, not a measurement: the verifier can
only cite IDs of ledger entries it was given, and the baseline arm reports the scorer's default
of 0 (`src/incident_evidence_compiler/evaluation/harness/runner.py:138-140`, `200-206`;
`src/incident_evidence_compiler/evaluation/harness/scoring.py:59`).

| Date | Freeze commit | Arm | Top-1 | Top-3 | MRR | Abstention | Invalid IDs |
|---|---|---|---|---|---|---|---|
| 2026-07-19 | `0a7854e` | baseline | 0.766667 | 0.877778 | 0.832565 | 0.000000 | 0 |
| 2026-07-19 | `0a7854e` | gemini | 0.155556 | 0.155556 | 0.155556 | 0.577778 | 0 |

Answered-only (over the cases where the system committed to a ranking): baseline is unchanged
(0 abstentions); gemini answered 38/90 with Top-1 0.368421, Top-3 0.368421, MRR 0.368421.

Reading: the deterministic baseline localizes the held-out RE2-TT (train-ticket) faults well
(Top-1 0.77). The verifier-gated Gemini arm is deliberately conservative, it abstains on 52/90
cases rather than assert an unverified conclusion, and underperforms the baseline where it does
commit. That is the fail-closed design working as intended, not a regression: on this held-out
system the restricted-hypothesis + deterministic-verifier path trades recall for the guarantee
that every asserted conclusion carries a passing verifier trace. No tuning was or will be done
against TT.

Note on artifact prose: the committed JSONs carry a generic `notes` string that says
"development split"; it is boilerplate from `_build_artifact` and is not split-specific. The
authoritative split is the machine-readable `dataset.split` field, which is `"TT"` in both files.

## Future upgrades (backlog, not part of the one held-out run)

- If RE2-SS is later promoted to a secondary development set (open decision), calibrate the
  abstention threshold there, never on TT.
- OpenTelemetry spans + estimated-cost metric during the sealed rerun (ADR 0015 deferral).
