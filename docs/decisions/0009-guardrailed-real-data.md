# ADR 0009: Guardrailed local acquisition of RCAEval RE2-OB

- Status: Accepted
- Date: 2026-07-17
- Decision owners: Aswani and the project orchestrator

## Context

Phases 0–3 were built and verified entirely against synthetic fixtures. The Phase 1 RCAEval
adapter (`src/incident_evidence_compiler/evaluation/rcaeval/`) encodes assumptions about the
real RE2 layout — evaluator-discovered metric files, sibling `inject_time.txt`, and a leakage
boundary that keeps source paths and ground-truth labels out of investigation code — but those
assumptions have never been exercised against the actual archive. The upcoming persistence and
evaluation phases need development grounded in the real data shapes, not only synthetic ones.

The dataset is pinned and documented in `docs/datasets/rcaeval-re2.md`: RCAEval release `1.2.0`
at commit `bc49dbd85bd14032101fb9a69a5a37e9d6d55178`, Zenodo record `14590730`. `RE2-OB.zip` is
1,191,025,569 bytes with `md5:b9e23f8842c404b396ffd2becff15de4`.

Two standing constraints shape how the data may be used:

- Raw RCAEval data is separately licensed (upstream repo states MIT; Zenodo metadata states
  `cc-by-4.0`) and must never be committed or redistributed (ADR 0001, dataset record).
- The project validator (`_validate_dataset_policy`) walks the working tree and forbids any raw
  archive or extracted `RE2-*` tree inside the repository root, independently of `.gitignore`.
  This is a stronger guarantee than ignore rules and must remain intact.

## Decision

1. Download `RE2-OB.zip` now and verify it against the pinned MD5 before use. RE2-OB is the
   development/calibration split (accepted decisions); a mismatch aborts use.
2. Store and extract the archive **outside the repository root** (under
   `C:\Users\aswan\RAG\rcaeval-data\RE2\RE2-OB` locally), so the validator's no-raw-data
   guarantee stays intact without being weakened. The loader reads real data via an explicit
   local path, never a committed one.
3. Keep the raw archive and extracted tree out of version control. As defense-in-depth, add
   `data/RE2/` and `*.zip` to `.gitignore` even though the canonical location is outside the repo.
4. Ground development in real shapes: run the existing Phase 1 loader against a real case
   directory as local verification. This smoke check is not committed.
5. Keep CI hermetic. Automated tests and the phase gate continue to run only against committed
   synthetic fixtures and deterministic fakes; they never require the real archive, network, or
   credentials.
6. Deriving a small sanitized, label-free committed fixture from real shapes is deferred to its
   own reviewable slice; this ADR does not commit any derived data.
7. RE2-TT stays sealed by default and is not downloaded here. RE2-SS remains reserved.

## Consequences

### Positive

- Development is grounded in the real RE2-OB layout while the repository, its history, and CI
  remain free of separately-licensed data.
- The validator's working-tree guarantee is preserved unchanged; no hole is poked in it.
- Checksum verification before use makes the acquisition auditable and reproducible against the
  pinned record.

### Cost

- The real data path is machine-local and absolute, so the smoke check is not reproducible in CI
  by design; reproducibility for automated tests rests on the committed synthetic fixtures.
- A future fixture-derivation slice is still required before real shapes are represented in the
  committed test suite.

## Verification (2026-07-17)

The acquisition and smoke check were executed:

- `RE2-OB.zip` downloaded from the pinned Zenodo record; size `1191025569` bytes and
  `md5:b9e23f8842c404b396ffd2becff15de4` both match the pinned manifest exactly.
- Extracted to the out-of-repo path; the pinned `RE2-OB/<service>_<fault>/<repetition>/` layout
  is present. Discovery finds 90 cases (30 fault groups × repetitions 1–3); the sibling
  `multi-source-data` directories are correctly not discovered as metric cases.
- Running the committed Phase 1 loader against the real split surfaced a real-shape gap: only
  19 of 90 cases parse. 70 fail `invalid_number` and 1 fails `non_finite_number`, because real
  RE2-OB metric CSVs contain empty (missing) cells and occasional non-finite values — for example
  `checkoutservice_cpu/1/simple_metrics.csv` has empty cells where services do not emit a given
  signal during part of the window. The committed strict parser rejects the entire case on the
  first such cell.

This is the intended value of grounding in real shapes. Handling missing and non-finite metric
cells (reject the case, drop the point, or represent an explicit gap) is a domain decision that
affects evidence semantics — missing data is not zero — and is deliberately deferred to its own
slice with tests, ahead of any real evaluation. It is recorded as a new open decision, not fixed
here.

## Rejected alternatives

- **Download into `data/RE2/` inside the repo and relax the validator**: would weaken the
  validator's no-raw-data guarantee for the entire project to serve a local convenience. Rejected.
- **Commit a real sub-sample now**: risks redistributing separately-licensed data and leaking
  ground-truth labels before a sanitization step exists. Rejected; fixture derivation is a
  separate guarded slice.
- **Defer the download and keep building on synthetic shapes only**: leaves the loader's real-data
  assumptions unverified going into persistence and evaluation. Rejected.
