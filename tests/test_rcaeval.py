from __future__ import annotations

import dataclasses
import json
import logging
import tempfile
import unittest
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest import mock
from uuid import UUID

from incident_evidence_compiler.domain import CaseId
from incident_evidence_compiler.evaluation.rcaeval import (
    EvaluationSidecar,
    LoaderLimits,
    LoadErrorCode,
    RcaevalAdapter,
    RcaevalLoadError,
    SidecarEntry,
    authorize_sealed_split,
    load_manifest,
    persist_sidecar,
    random_case_id,
    sidecar_json,
)
from incident_evidence_compiler.evaluation.rcaeval.csv_loader import parse_case
from incident_evidence_compiler.evaluation.rcaeval.discovery import DiscoveredCase
from incident_evidence_compiler.evaluation.rcaeval.ids import RcaevalSplit, unique_case_id

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "rcaeval" / "RE2-OB"
MANIFEST_PATH = ROOT / "docs" / "datasets" / "rcaeval-re2.manifest.json"
UUIDS = tuple(UUID(f"00000000-0000-4000-8000-{index:012d}") for index in range(1, 20))


def sequence_factory(values: tuple[UUID, ...] = UUIDS) -> Callable[[], CaseId]:
    iterator = iter(values)
    return lambda: CaseId(next(iterator))


@contextmanager
def case_tree(
    csv_text: str,
    injection: str = "2026-01-01T00:01:00Z",
    *,
    metric_name: str = "data.csv",
) -> Iterator[tuple[tempfile.TemporaryDirectory[str], Path, Path]]:
    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name) / "RE2-OB"
    case = root / "CANARYSERVICE_CANARYFAULT" / "DO_NOT_LEAK_PATH"
    case.mkdir(parents=True)
    (case / metric_name).write_text(csv_text, encoding="utf-8")
    (case / "inject_time.txt").write_text(injection, encoding="utf-8")
    try:
        yield temporary, root, case
    finally:
        temporary.cleanup()


class ManifestTests(unittest.TestCase):
    def test_manifest_pins_all_authoritative_metadata(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)
        self.assertEqual(manifest.release, "1.2.0")
        self.assertEqual(manifest.annotated_tag_object, "5f22afb1cd9e383f52c41c2e8e99c8ef930db5d8")
        self.assertEqual(manifest.release_commit, "bc49dbd85bd14032101fb9a69a5a37e9d6d55178")
        self.assertEqual(str(manifest.metadata_retrieved_on), "2026-07-16")
        expected = {
            "OB": (1_191_025_569, "b9e23f8842c404b396ffd2becff15de4"),
            "SS": (245_629_018, "bd747a8fc7c5be00c613e13fbf9dd74b"),
            "TT": (2_801_345_134, "a7fbcd1ada406067dcc50771ae398408"),
        }
        self.assertEqual(
            {item.split: (item.bytes, item.checksum_value) for item in manifest.archives},
            expected,
        )
        self.assertEqual(
            {notice.identifier for notice in manifest.license_notices}, {"MIT", "CC-BY-4.0"}
        )

    def test_manifest_is_strict_and_has_no_payload_or_download_api(self) -> None:
        value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        value["unexpected"] = True
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid_manifest"):
                load_manifest(path)
        manifest_module = __import__(
            "incident_evidence_compiler.evaluation.rcaeval.manifest", fromlist=["*"]
        )
        names = dir(manifest_module)
        self.assertFalse(
            any("download" in name.lower() or "fetch" in name.lower() for name in names)
        )


class LimitsAndIdTests(unittest.TestCase):
    def test_exact_default_limits_and_invalid_overrides(self) -> None:
        self.assertEqual(
            dataclasses.astuple(LoaderLimits()),
            (67_108_864, 4_096, 250_000, 2_048, 65_536, 512, 100_000),
        )
        for field in (item.name for item in dataclasses.fields(LoaderLimits)):
            with self.subTest(field=field):
                values = dataclasses.asdict(LoaderLimits())
                values[field] = 0
                with self.assertRaisesRegex(ValueError, "invalid_loader_limits"):
                    LoaderLimits(**values)

    def test_random_ids_are_uuid4_and_differ(self) -> None:
        first = random_case_id()
        second = random_case_id()
        self.assertEqual((first.value.version, second.value.version), (4, 4))
        self.assertNotEqual(first, second)

    def test_deterministic_factory_and_collision_policy(self) -> None:
        assigned: set[CaseId] = set()
        factory = sequence_factory((UUIDS[0], UUIDS[0], UUIDS[1]))
        self.assertEqual(unique_case_id(factory, assigned), CaseId(UUIDS[0]))
        self.assertEqual(unique_case_id(factory, assigned), CaseId(UUIDS[1]))
        colliding = sequence_factory((UUIDS[0],) * 8)
        with self.assertRaises(RcaevalLoadError) as caught:
            unique_case_id(colliding, assigned)
        self.assertEqual(caught.exception.code, LoadErrorCode.CASE_ID_COLLISION)

    def test_factory_rejects_non_v4_or_malformed_without_echo(self) -> None:
        for factory in (lambda: object(), lambda: CaseId(UUID(int=0))):
            with self.subTest(factory=factory):
                with self.assertRaises(RcaevalLoadError) as caught:
                    unique_case_id(factory, set())  # type: ignore[arg-type]
                self.assertEqual(caught.exception.code, LoadErrorCode.INVALID_CASE_ID)


class AdapterTests(unittest.TestCase):
    def test_mixed_fixture_uses_preferred_file_per_case(self) -> None:
        batch = RcaevalAdapter(case_id_factory=sequence_factory()).load(FIXTURE_ROOT, "OB")
        self.assertEqual(len(batch.cases), 2)
        by_signal = {case.signals[0].key.value: case for case in batch.cases}
        self.assertEqual(
            tuple(point.value for point in by_signal["cpu"].signals[0].points),
            (1, 1, 8, 8),
        )
        self.assertEqual(
            tuple(point.value for point in by_signal["errors"].signals[0].points),
            (0, 0, 4, 4),
        )

    def test_malformed_preferred_file_does_not_fall_back(self) -> None:
        with case_tree("bad-header\n", metric_name="data.csv") as (_, root, case):
            (case / "simple_metrics.csv").write_text(
                "time,x\n2026-01-01T00:00:00Z,1\n2026-01-01T00:01:00Z,2\n",
                encoding="utf-8",
            )
            with self.assertRaises(RcaevalLoadError) as caught:
                RcaevalAdapter(case_id_factory=sequence_factory()).load(root, "OB")
            self.assertEqual(caught.exception.code, LoadErrorCode.UNSUPPORTED_CSV_SCHEMA)

    def test_missing_injection_and_invalid_utf8_are_typed(self) -> None:
        with case_tree("time,x\n2026-01-01T00:00:00Z,1\n2026-01-01T00:01:00Z,2\n") as (
            _,
            root,
            case,
        ):
            (case / "inject_time.txt").unlink()
            with self.assertRaises(RcaevalLoadError) as missing:
                RcaevalAdapter(case_id_factory=sequence_factory()).load(root, "OB")
            self.assertEqual(missing.exception.code, LoadErrorCode.MISSING_INJECTION_TIME)
        with case_tree("placeholder") as (_, root, case):
            (case / "data.csv").write_bytes(b"time,x\n0,\xff\n1,2\n")
            with self.assertRaises(RcaevalLoadError) as invalid:
                RcaevalAdapter(case_id_factory=sequence_factory()).load(root, "OB")
            self.assertEqual(invalid.exception.code, LoadErrorCode.INVALID_ENCODING)

    def test_injection_at_first_or_last_observation_is_accepted(self) -> None:
        csv_text = "time,x\n0,1\n1,2\n"
        for injection in ("0", "1"):
            with self.subTest(injection=injection):
                with case_tree(csv_text, injection) as (_, root, _):
                    batch = RcaevalAdapter(case_id_factory=sequence_factory()).load(root, "OB")
                    self.assertEqual(len(batch.cases), 1)

    def test_ss_and_tt_are_guarded_before_filesystem_io(self) -> None:
        adapter = RcaevalAdapter(case_id_factory=sequence_factory())
        with mock.patch("pathlib.Path.is_dir") as is_dir:
            with self.assertRaises(RcaevalLoadError) as ss:
                adapter.load(Path("DO_NOT_LEAK_PATH"), "SS")
            with self.assertRaises(RcaevalLoadError) as tt:
                adapter.load(Path("DO_NOT_LEAK_PATH"), "TT")
            is_dir.assert_not_called()
        self.assertEqual(ss.exception.code, LoadErrorCode.SPLIT_RESERVED)
        self.assertEqual(tt.exception.code, LoadErrorCode.SEALED_SPLIT_DENIED)

    def test_explicit_tt_permit_allows_only_local_loading(self) -> None:
        permit = authorize_sealed_split(confirmed=True, reason="local held-out authorization")
        self.assertNotIn("reason", repr(permit).lower())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "RE2-TT"
            root.mkdir()
            batch = RcaevalAdapter().load(root, "TT", sealed_permit=permit)
            self.assertEqual(batch.cases, ())
        with self.assertRaises(RcaevalLoadError):
            authorize_sealed_split(confirmed=False, reason="no")

    def test_case_and_scan_bounds_are_inclusive(self) -> None:
        csv_text = "time,x\n2026-01-01T00:00:00Z,1\n2026-01-01T00:01:00Z,2\n"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "RE2-OB"
            for index in range(2):
                case = root / f"SERVICE{index}_FAULT" / "rep"
                case.mkdir(parents=True)
                (case / "data.csv").write_text(csv_text, encoding="utf-8")
                (case / "inject_time.txt").write_text("2026-01-01T00:01:00Z", encoding="utf-8")
            accepted = RcaevalAdapter(
                limits=LoaderLimits(max_discovered_cases=2), case_id_factory=sequence_factory()
            ).load(root, "OB")
            self.assertEqual(len(accepted.cases), 2)
            with self.assertRaises(RcaevalLoadError) as caught:
                RcaevalAdapter(
                    limits=LoaderLimits(max_discovered_cases=1),
                    case_id_factory=sequence_factory(),
                ).load(root, "OB")
            self.assertEqual(caught.exception.code, LoadErrorCode.CASE_LIMIT_EXCEEDED)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "RE2-OB"
            root.mkdir()
            (root / "one").mkdir()
            RcaevalAdapter(limits=LoaderLimits(max_scanned_entries=1)).load(root, "OB")
            (root / "two").mkdir()
            with self.assertRaises(RcaevalLoadError) as caught:
                RcaevalAdapter(limits=LoaderLimits(max_scanned_entries=1)).load(root, "OB")
            self.assertEqual(caught.exception.code, LoadErrorCode.SCAN_LIMIT_EXCEEDED)


class CsvBoundaryTests(unittest.TestCase):
    VALID = "time,x\n2026-01-01T00:00:00Z,1\n2026-01-01T00:01:00Z,2\n"

    def error_for(
        self,
        csv_text: str,
        *,
        injection: str = "2026-01-01T00:01:00Z",
        limits: LoaderLimits | None = None,
    ) -> LoadErrorCode:
        with case_tree(csv_text, injection) as (_, root, _):
            with self.assertRaises(RcaevalLoadError) as caught:
                RcaevalAdapter(
                    limits=limits if limits is not None else LoaderLimits(),
                    case_id_factory=sequence_factory(),
                ).load(root, "OB")
            return caught.exception.code

    def test_bom_utf8_and_unix_or_rfc3339_timestamps(self) -> None:
        text = "\ufefftime,x\n1767225600,1\n2026-01-01T00:01:00+00:00,2\n"
        with case_tree(text, "1767225660") as (_, root, _):
            batch = RcaevalAdapter(case_id_factory=sequence_factory()).load(root, "OB")
            self.assertEqual(len(batch.cases[0].signals[0].points), 2)

    def test_schema_row_number_and_timestamp_failures_are_typed(self) -> None:
        cases = {
            LoadErrorCode.UNSUPPORTED_CSV_SCHEMA: "time,x,x\n0,1,2\n",
            LoadErrorCode.ROW_WIDTH_MISMATCH: "time,x\n0,1,2\n",
            LoadErrorCode.INVALID_NUMBER: "time,x\n0,abc\n",
            LoadErrorCode.INVALID_TIMESTAMP: "time,x\nnaive,1\n",
            LoadErrorCode.TIMESTAMPS_NOT_ORDERED: "time,x\n2,1\n1,2\n",
        }
        for expected, text in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(self.error_for(text, injection="1"), expected)

    def test_missing_and_non_finite_cells_drop_points_not_case(self) -> None:
        # Column 'a' has an empty (missing) cell at t=1; column 'b' has a
        # non-finite cell at t=2. Both are dropped for that signal only; the
        # case still loads and the other columns at those timestamps survive.
        text = "time,a,b\n0,1,10\n1,,11\n2,3,nan\n3,4,13\n"
        with case_tree(text, injection="2") as (_, root, _):
            batch = RcaevalAdapter(case_id_factory=sequence_factory()).load(root, "OB")
        self.assertEqual(len(batch.cases), 1)
        signals = {signal.key.value: signal for signal in batch.cases[0].signals}
        self.assertEqual(tuple(point.value for point in signals["a"].points), (1, 3, 4))
        self.assertEqual(tuple(point.value for point in signals["b"].points), (10, 11, 13))
        # The dropped observations leave gaps in each affected signal's timeline;
        # missing data is never coerced to zero.
        self.assertEqual([point.observed_at.timestamp() for point in signals["a"].points][1], 2.0)
        self.assertEqual([point.observed_at.timestamp() for point in signals["b"].points][2], 3.0)

    def test_parse_case_reports_exact_dropped_cell_count(self) -> None:
        text = "time,a,b\n0,1,10\n1,,11\n2,3,nan\n3,4,13\n"
        with case_tree(text, injection="2") as (_, _, case):
            discovered = DiscoveredCase(
                directory=case,
                metric_file=case / "data.csv",
                injection_file=case / "inject_time.txt",
                source_locator="redacted",
                root_cause_service="svc",
                injected_fault_type="fault",
                repetition="1",
            )
            parsed = parse_case(discovered, CaseId(UUIDS[0]), LoaderLimits())
        self.assertEqual(parsed.dropped_cell_count, 2)
        self.assertEqual(parsed.row_count, 4)
        self.assertIn("dropped_cell_count=2", repr(parsed))

    def test_fully_empty_column_yields_empty_signal(self) -> None:
        text = "time,a,b\n0,1,\n1,2,\n"
        with case_tree(text, injection="1") as (_, root, _):
            batch = RcaevalAdapter(case_id_factory=sequence_factory()).load(root, "OB")
        signals = {signal.key.value: signal for signal in batch.cases[0].signals}
        self.assertEqual(tuple(point.value for point in signals["a"].points), (1, 2))
        self.assertEqual(signals["b"].points, ())

    def test_file_row_column_and_field_limits_are_exact(self) -> None:
        with case_tree(self.VALID) as (_, root, case):
            actual_size = (case / "data.csv").stat().st_size
            accepted = RcaevalAdapter(
                limits=LoaderLimits(max_metric_file_bytes=actual_size),
                case_id_factory=sequence_factory(),
            ).load(root, "OB")
            self.assertEqual(len(accepted.cases), 1)
        self.assertEqual(
            self.error_for(
                self.VALID,
                limits=LoaderLimits(max_metric_file_bytes=actual_size - 1),
            ),
            LoadErrorCode.METRIC_FILE_TOO_LARGE,
        )
        self.assertEqual(
            self.error_for(self.VALID, limits=LoaderLimits(max_data_rows=1)),
            LoadErrorCode.ROW_LIMIT_EXCEEDED,
        )
        self.assertEqual(
            self.error_for(self.VALID, limits=LoaderLimits(max_columns=1)),
            LoadErrorCode.COLUMN_LIMIT_EXCEEDED,
        )
        long_field = "time,x\n0,12345\n1,1\n"
        self.assertEqual(
            self.error_for(long_field, injection="1", limits=LoaderLimits(max_field_characters=4)),
            LoadErrorCode.FIELD_TOO_LONG,
        )

    def test_overwide_data_record_hits_column_limit_before_row_width(self) -> None:
        overwide = "time,x\n0," + ",".join("1" for _ in range(128)) + "\n"
        self.assertEqual(
            self.error_for(overwide, injection="0", limits=LoaderLimits(max_columns=2)),
            LoadErrorCode.COLUMN_LIMIT_EXCEEDED,
        )

    def test_width_scanner_ignores_delimiters_inside_quoted_fields(self) -> None:
        for value in ('"1,2"', '"1""2"'):
            with self.subTest(value=value):
                self.assertEqual(
                    self.error_for(
                        f"time,x\n0,{value}\n",
                        injection="0",
                        limits=LoaderLimits(max_columns=2),
                    ),
                    LoadErrorCode.INVALID_NUMBER,
                )

    def test_injection_size_encoding_nul_and_window_bounds(self) -> None:
        self.assertEqual(
            self.error_for(self.VALID, limits=LoaderLimits(max_inject_time_file_bytes=2)),
            LoadErrorCode.INJECTION_FILE_TOO_LARGE,
        )
        self.assertEqual(
            self.error_for("time,x\n0,1\x00\n1,2\n", injection="1"),
            LoadErrorCode.INVALID_ENCODING,
        )
        for injection in ("2025-01-01T00:00:00Z", "2027-01-01T00:00:00Z"):
            with self.subTest(injection=injection):
                self.assertEqual(
                    self.error_for(self.VALID, injection=injection),
                    LoadErrorCode.INVALID_TIMESTAMP,
                )


class SidecarAndLeakageTests(unittest.TestCase):
    def test_sidecar_is_explicit_sensitive_json_and_persists_atomically(self) -> None:
        case_id = CaseId(UUIDS[0])
        sidecar = EvaluationSidecar(
            "1.2.0",
            "bc49dbd85bd14032101fb9a69a5a37e9d6d55178",
            (
                SidecarEntry(
                    case_id,
                    RcaevalSplit.OB,
                    "CANARYSERVICE_CANARYFAULT/DO_NOT_LEAK_PATH",
                    "CANARYSERVICE",
                    "CANARYFAULT",
                    "DO_NOT_LEAK_PATH",
                    ("CANARYSERVICE", "CANARYFAULT"),
                ),
            ),
        )
        self.assertEqual(repr(sidecar), "EvaluationSidecar(entry_count=1)")
        self.assertIn("CANARYSERVICE", sidecar_json(sidecar))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts" / "evaluation-sidecars"
            destination = root / "run.json"
            persist_sidecar(sidecar, destination, sidecar_root=root)
            self.assertEqual(destination.read_text(encoding="utf-8"), sidecar_json(sidecar))
            with self.assertRaises(RcaevalLoadError):
                persist_sidecar(sidecar, Path(temporary) / "outside.json", sidecar_root=root)

    def test_investigation_objects_errors_and_logs_do_not_leak_labels_or_locator(self) -> None:
        batch = RcaevalAdapter(case_id_factory=sequence_factory()).load(FIXTURE_ROOT, "OB")
        canaries = ("CANARYSERVICE", "CANARYFAULT", "DO_NOT_LEAK_PATH", str(FIXTURE_ROOT))
        investigation_surfaces = [repr(batch), *(repr(case) for case in batch.cases)]
        investigation_surfaces.extend(
            json.dumps(dataclasses.asdict(case), default=str) for case in batch.cases
        )
        logger = logging.getLogger("incident_evidence_compiler.evaluation.rcaeval")
        with self.assertLogs(logger, level="INFO") as captured:
            logger.info("case_loaded", extra={"case_id": str(batch.cases[0].case_id)})
        investigation_surfaces.extend(captured.output)
        with case_tree("bad\n") as (_, root, _):
            with self.assertRaises(RcaevalLoadError) as caught:
                RcaevalAdapter(case_id_factory=sequence_factory()).load(root, "OB")
            investigation_surfaces.extend((str(caught.exception), repr(caught.exception)))
        combined = "\n".join(investigation_surfaces)
        for canary in canaries:
            with self.subTest(canary=canary):
                self.assertNotIn(canary, combined)

    def test_investigator_boundary_receives_no_sidecar(self) -> None:
        batch = RcaevalAdapter(case_id_factory=sequence_factory()).load(FIXTURE_ROOT, "OB")
        received: list[object] = []

        def investigate(case: object) -> None:
            received.append(case)

        for case in batch.cases:
            investigate(case)
        self.assertEqual(received, list(batch.cases))
        self.assertTrue(all(not isinstance(value, EvaluationSidecar) for value in received))


if __name__ == "__main__":
    unittest.main()
