"""Unit tests for the shared demo formatters in ``scripts/_demo_common.py``.

The module is loaded by path, the same way ``tests/test_validate_project.py`` loads
``scripts/validate_project.py``: ``scripts`` is a plain directory, not an installed package, so
there is nothing to import by name. The module object is annotated ``Any`` because a
``ModuleType`` has no statically known attributes under mypy strict.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEMO_COMMON_PATH = ROOT / "scripts" / "_demo_common.py"
SPEC = importlib.util.spec_from_file_location("_demo_common", DEMO_COMMON_PATH)
assert SPEC is not None and SPEC.loader is not None
demo_common: Any = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo_common)

# Hex strings copied from a real report served by GET /investigations/{id}/report against the
# committed RE2-OB fixture: every float crosses the wire as float.hex() (ADR 0019).
_MINIMUM_SCORE = "0x1.0000000000000p+0"  # 1.0
_CPU_SUSPICION = "0x1.f1c71c71c71c7p+4"  # 31.111...
_LATENCY_SUSPICION = "0x1.e79e79e79e79ep+0"  # 1.904...


def _candidate(signal_key: str, suspicion: str, *, signed: str | None = None) -> dict[str, Any]:
    return {
        "post_median": "0x1.0000000000000p+3",
        "pre_median": "0x1.0000000000000p+0",
        "signal_key": signal_key,
        "signed_score": suspicion if signed is None else signed,
        "suspicion_score": suspicion,
    }


def _ranking_report() -> dict[str, Any]:
    return {
        "baseline_ranking": {
            "abstention_reason": None,
            "candidates": [
                _candidate("cpu", _CPU_SUSPICION),
                _candidate("latency", _LATENCY_SUSPICION),
            ],
            "kind": "ranking",
            "lead": "0x1.d34d34d34d34dp+4",
            "policy": {"minimum_margin": "0x0.0p+0", "minimum_score": _MINIMUM_SCORE},
            "schema_version": "baseline-ranking.v1",
            "second_score": _LATENCY_SUSPICION,
            "top_score": _CPU_SUSPICION,
        }
    }


class FormatBaselineRankingTests(unittest.TestCase):
    def test_ranking_is_rendered_with_decoded_hex_floats(self) -> None:
        rendered = demo_common.format_baseline_ranking(_ranking_report())
        self.assertEqual(
            rendered,
            "baseline ranking (deterministic, no model): kind=ranking minimum_score=1.00\n"
            "  1. cpu       suspicion=31.11  direction=increase\n"
            "  2. latency   suspicion=1.90   direction=increase",
        )

    def test_negative_signed_score_reads_as_a_decrease(self) -> None:
        report = _ranking_report()
        report["baseline_ranking"]["candidates"] = [
            _candidate("cpu", _CPU_SUSPICION, signed="-" + _CPU_SUSPICION)
        ]
        rendered = demo_common.format_baseline_ranking(report)
        self.assertEqual(
            rendered,
            "baseline ranking (deterministic, no model): kind=ranking minimum_score=1.00\n"
            "  1. cpu   suspicion=31.11  direction=decrease",
        )

    def test_candidate_list_is_truncated_to_the_limit_and_says_so(self) -> None:
        report = _ranking_report()
        report["baseline_ranking"]["candidates"] = [
            _candidate(f"signal-{index}", _CPU_SUSPICION) for index in range(4)
        ]
        rendered = demo_common.format_baseline_ranking(report, limit=2)
        lines = rendered.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[1].startswith("  1. signal-0"))
        self.assertTrue(lines[2].startswith("  2. signal-1"))
        self.assertEqual(lines[3], "  ... and 2 more candidates")

    def test_abstention_states_the_reason_and_still_lists_candidates(self) -> None:
        report = {
            "baseline_ranking": {
                "abstention_reason": "weak_evidence",
                "candidates": [_candidate("cpu", _LATENCY_SUSPICION)],
                "kind": "abstention",
                "lead": None,
                "policy": {"minimum_score": _MINIMUM_SCORE},
                "schema_version": "baseline-ranking.v1",
                "second_score": None,
                "top_score": _LATENCY_SUSPICION,
            }
        }
        rendered = demo_common.format_baseline_ranking(report)
        self.assertEqual(
            rendered,
            "baseline ranking (deterministic, no model): kind=abstention minimum_score=1.00\n"
            "  abstained: weak_evidence\n"
            "  1. cpu   suspicion=1.90  direction=increase",
        )

    def test_missing_baseline_ranking_is_reported_as_not_present(self) -> None:
        expected = "baseline ranking: not present (report predates migration 0002)"
        self.assertEqual(demo_common.format_baseline_ranking({"baseline_ranking": None}), expected)
        self.assertEqual(demo_common.format_baseline_ranking({}), expected)

    def test_malformed_payloads_never_raise(self) -> None:
        unavailable = "baseline ranking: unavailable"
        malformed: tuple[dict[str, Any], ...] = (
            {"baseline_ranking": []},
            {"baseline_ranking": {"kind": "ranking"}},
            {"baseline_ranking": {"kind": "ranking", "candidates": [], "policy": {}}},
            {
                "baseline_ranking": {
                    "candidates": [_candidate("cpu", _CPU_SUSPICION)],
                    "kind": "guesswork",
                    "policy": {"minimum_score": _MINIMUM_SCORE},
                }
            },
            {
                "baseline_ranking": {
                    "candidates": [_candidate("cpu", "not-a-hex-float")],
                    "kind": "ranking",
                    "policy": {"minimum_score": _MINIMUM_SCORE},
                }
            },
        )
        for report in malformed:
            with self.subTest(report=report):
                self.assertEqual(demo_common.format_baseline_ranking(report), unavailable)


class FormatPredicatesTests(unittest.TestCase):
    def test_one_line_per_predicate(self) -> None:
        report = {
            "report": {
                "verdict": "supported",
                "predicate_results": [
                    {
                        "contradicting_evidence_ids": [],
                        "observed_direction": "increase",
                        "predicate_id": "p1",
                        "supporting_evidence_ids": ["sha256:abc"],
                        "verdict": "supported",
                    },
                    {
                        "contradicting_evidence_ids": ["sha256:def"],
                        "observed_direction": "decrease",
                        "predicate_id": "p2",
                        "supporting_evidence_ids": [],
                        "verdict": "refuted",
                    },
                ],
            }
        }
        self.assertEqual(
            demo_common.format_predicates(report),
            "  p1: supported observed=increase supporting=1 contradicting=0\n"
            "  p2: refuted observed=decrease supporting=0 contradicting=1",
        )

    def test_absent_predicate_results_render_as_empty_text(self) -> None:
        self.assertEqual(demo_common.format_predicates({"report": {"verdict": "unknown"}}), "")
        self.assertEqual(demo_common.format_predicates({}), "")

    def test_partial_predicate_does_not_raise(self) -> None:
        report = {"report": {"predicate_results": [{"predicate_id": "p1"}]}}
        self.assertEqual(
            demo_common.format_predicates(report),
            "  p1: ? observed=None supporting=0 contradicting=0",
        )


if __name__ == "__main__":
    unittest.main()
