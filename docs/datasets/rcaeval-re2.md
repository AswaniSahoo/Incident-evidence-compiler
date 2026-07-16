# RCAEval RE2 Dataset Record

## Pinned sources

- Repository: https://github.com/phamquiluan/RCAEval
- Release: `1.2.0`
- Annotated tag object: `5f22afb1cd9e383f52c41c2e8e99c8ef930db5d8`
- Release commit: `bc49dbd85bd14032101fb9a69a5a37e9d6d55178`
- Archive record: https://zenodo.org/records/14590730
- Archive API: https://zenodo.org/api/records/14590730
- Record DOI: `10.5281/zenodo.14590730`
- Metadata publication date: 2024-01-03
- Record creation timestamp: `2025-01-03T12:06:03.078444+00:00`
- Metadata retrieved: 2026-07-16

The API's publication date and record creation date are different fields and are intentionally recorded separately.

## License record

The pinned upstream RCAEval repository's root `LICENSE` is MIT, and its release README says code implemented by the authors and their datasets are distributed under MIT. The Zenodo API metadata for record `14590730` identifies the archive license as `cc-by-4.0`.

This project does not resolve that discrepancy. It records both notices, applies CC-BY-4.0 attribution requirements to archive use, retains source attribution, and does not redistribute raw archives.

## RE2 archives

| Archive | Role | Bytes | Checksum |
|---|---|---:|---|
| `RE2-OB.zip` | Development/calibration | 1,191,025,569 | `md5:b9e23f8842c404b396ffd2becff15de4` |
| `RE2-SS.zip` | Reserved | 245,629,018 | `md5:bd747a8fc7c5be00c613e13fbf9dd74b` |
| `RE2-TT.zip` | Sealed evaluation | 2,801,345,134 | `md5:a7fbcd1ada406067dcc50771ae398408` |

Exact byte counts and checksums come from the pinned Zenodo API response. The large archives were not downloaded during design.

## Pinned evaluator layout

RCAEval release `1.2.0` maps systems to:

```text
data/RE2/RE2-OB
data/RE2/RE2-SS
data/RE2/RE2-TT
```

Its evaluator recursively discovers `data.csv`. Only when no `data.csv` exists anywhere under the selected system does it globally fall back to `simple_metrics.csv`. For each case it reads sibling `inject_time.txt`. It derives ground truth from the parent-parent directory name using `<service>_<fault>` and derives the repetition/case from the immediate parent directory.

Phase 1 intentionally uses a safer per-case rule: prefer `data.csv` within a case directory, otherwise use `simple_metrics.csv`. A mixed-tree synthetic test records this deliberate difference.

The source path and parsed labels are evaluation metadata and must never enter investigation code.

## Multi-source compatibility note

The filename examples below come from the pinned notebook `docs/multi-source-rca-demo.ipynb` at release commit `bc49dbd85bd14032101fb9a69a5a37e9d6d55178` (Git blob `cb3d2697d87857b56d622b9673cfb1d259300197`):

```text
metrics.csv
logs.csv
traces.csv
logts.csv
tracets_lat.csv
tracets_err.csv
inject_time.txt
```

The notebook downloads a mutable release asset, so these names are compatibility evidence, not a guarantee about every RE2 archive case. Phase 1 loads evaluator-confirmed metric files plus `inject_time.txt` and fails explicitly on archive-specific differences.

## Leakage policy

Investigation code may receive:

- A random UUID case ID assigned at the evaluation boundary
- System identifier (`OB`, `SS`, or `TT`)
- UTC telemetry window and injection timestamp
- Service and signal names present in telemetry columns
- Normalized evidence values and source kind

An evaluation-only sidecar owns:

- Relative/absolute source locator
- Root-cause service
- Injected fault type
- Archive split labels used as answers
- The mapping from random case ID to source case when local replay requires it

The sidecar is local and ignored. It is never passed to investigation code. Tests inject a deterministic ID factory and verify serialization, object representations, captured logs, and malformed-input errors contain no locator or ground-truth values.

RE2-TT access is denied by default and requires an explicit sealed-data override. Held-out scores are not produced in Phase 1 unless Aswani provides the archive and explicitly authorizes opening the sealed split.
