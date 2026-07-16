from __future__ import annotations

import inspect
import itertools
import math
import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from uuid import UUID

import incident_evidence_compiler.domain as domain
from incident_evidence_compiler.domain import (
    AbstentionReason,
    BaselineAbstention,
    BaselineComputationError,
    BaselinePolicy,
    BaselineRanking,
    CaseId,
    DuplicateSignalError,
    EvidenceId,
    IncidentId,
    IncidentWindow,
    InvalidBaselineConfigurationError,
    InvalidIdentifierError,
    InvalidIncidentWindowError,
    InvalidMetricPointError,
    InvalidMetricSignalError,
    InvalidTimestampError,
    MetricPoint,
    MetricSignal,
    RunId,
    SignalBaselineInput,
    SignalKey,
    TenantId,
    rank_metric_shifts,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


class NoOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> None:
        return None

    def dst(self, dt: datetime | None) -> None:
        return None

    def tzname(self, dt: datetime | None) -> None:
        return None


def point(minutes: int, value: float) -> MetricPoint:
    return MetricPoint(BASE + timedelta(minutes=minutes), value)


def signal(name: str, values: tuple[tuple[int, float], ...]) -> MetricSignal:
    return MetricSignal(SignalKey(name), (point(minute, value) for minute, value in values))


def baseline_input(
    name: str,
    pre: tuple[float, ...],
    post: tuple[float, ...],
    *,
    floor: float = 1.0,
) -> SignalBaselineInput:
    values = tuple((index, value) for index, value in enumerate(pre)) + tuple(
        (10 + index, value) for index, value in enumerate(post)
    )
    return SignalBaselineInput(signal(name, values), floor)


def window() -> IncidentWindow:
    return IncidentWindow(BASE, BASE + timedelta(minutes=10), BASE + timedelta(minutes=20))


def policy(
    *, count: int = 2, score: float = 0.0, margin: float = 0.0, relative: float = 0.0
) -> BaselinePolicy:
    return BaselinePolicy(count, score, margin, relative)


class IdentifierAndTimeTests(unittest.TestCase):
    def test_nominal_identifiers_accept_opaque_values_and_remain_distinct(self) -> None:
        identifiers = [TenantId("x"), IncidentId("x"), RunId("x"), EvidenceId("x")]
        self.assertEqual(len({type(value) for value in identifiers}), 4)
        case_id = CaseId(UUID("00000000-0000-4000-8000-000000000001"))
        self.assertEqual(str(case_id), "00000000-0000-4000-8000-000000000001")

    def test_text_identifiers_reject_empty_whitespace_and_non_string_safely(self) -> None:
        canary = "DO_NOT_LEAK_PATH"
        for identifier_type in (TenantId, IncidentId, RunId, EvidenceId):
            for value in ("", "  ", object()):
                with self.subTest(identifier=identifier_type, value=type(value)):
                    with self.assertRaises(InvalidIdentifierError) as caught:
                        identifier_type(value)  # type: ignore[arg-type]
                    self.assertEqual(str(caught.exception), "invalid_identifier")
                    self.assertNotIn(canary, str(caught.exception))

    def test_case_id_is_frozen_and_opaque(self) -> None:
        case_id = CaseId(UUID("00000000-0000-4000-8000-000000000001"))
        with self.assertRaises(FrozenInstanceError):
            case_id.value = UUID(int=0)  # type: ignore[misc]
        self.assertNotIn("path", repr(case_id).lower())

    def test_timestamps_normalize_to_utc_and_reject_naive_or_no_offset(self) -> None:
        eastern = timezone(timedelta(hours=5, minutes=30))
        normalized = MetricPoint(datetime(2026, 1, 1, 5, 30, tzinfo=eastern), 1)
        self.assertEqual(normalized.observed_at, BASE)
        for value in (datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=NoOffset())):
            with self.assertRaises(InvalidTimestampError):
                MetricPoint(value, 1)

    def test_window_accepts_equal_start_injection_and_enforces_interval(self) -> None:
        accepted = IncidentWindow(BASE, BASE, BASE + timedelta(seconds=1))
        self.assertEqual(accepted.start, accepted.injection)
        invalid = (
            (BASE, BASE - timedelta(seconds=1), BASE + timedelta(seconds=1)),
            (BASE, BASE + timedelta(seconds=1), BASE + timedelta(seconds=1)),
            (BASE, BASE + timedelta(seconds=2), BASE + timedelta(seconds=1)),
        )
        for args in invalid:
            with self.subTest(args=args):
                with self.assertRaises(InvalidIncidentWindowError):
                    IncidentWindow(*args)


class MetricTests(unittest.TestCase):
    def test_points_accept_finite_numbers_and_reject_invalid_values(self) -> None:
        for valid_value in (-1, 0, 1.5):
            self.assertEqual(MetricPoint(BASE, valid_value).value, float(valid_value))
        invalid_values: tuple[object, ...] = (True, math.nan, math.inf, -math.inf, "bad")
        for invalid_value in invalid_values:
            with self.subTest(value=invalid_value):
                with self.assertRaises(InvalidMetricPointError):
                    MetricPoint(BASE, invalid_value)  # type: ignore[arg-type]

    def test_signal_materializes_once_and_is_defensively_immutable(self) -> None:
        source = [point(0, 1)]
        metric = MetricSignal(SignalKey("cpu"), source)
        source.append(point(1, 2))
        self.assertEqual(len(metric.points), 1)
        self.assertIsInstance(metric.points, tuple)
        with self.assertRaises(FrozenInstanceError):
            metric.key = SignalKey("other")  # type: ignore[misc]

    def test_signal_accepts_empty_and_rejects_equal_or_decreasing_instants(self) -> None:
        self.assertEqual(MetricSignal(SignalKey("empty"), ()).points, ())
        for points in ((point(0, 1), point(0, 2)), (point(1, 1), point(0, 2))):
            with self.subTest(points=points):
                with self.assertRaises(InvalidMetricSignalError):
                    MetricSignal(SignalKey("cpu"), points)

    def test_timezone_normalization_makes_equal_instants_duplicates(self) -> None:
        same = MetricPoint(
            datetime(
                2026,
                1,
                1,
                5,
                30,
                tzinfo=timezone(timedelta(hours=5, minutes=30)),
            ),
            2,
        )
        with self.assertRaises(InvalidMetricSignalError):
            MetricSignal(SignalKey("cpu"), (point(0, 1), same))

    def test_signal_keys_reject_empty_without_normalizing_and_sort_lexically(self) -> None:
        with self.assertRaises(InvalidIdentifierError):
            SignalKey(" ")
        self.assertLess(SignalKey("A"), SignalKey("a"))
        self.assertEqual(SignalKey(" cpu ").value, " cpu ")


class BaselineFormulaTests(unittest.TestCase):
    def candidate(
        self,
        item: SignalBaselineInput,
        configured: BaselinePolicy | None = None,
    ) -> domain.SuspicionCandidate:
        result = rank_metric_shifts(window(), (item,), configured or policy())
        self.assertIsInstance(result, BaselineRanking)
        assert isinstance(result, BaselineRanking)
        return result.candidates[0]

    def test_odd_even_medians_and_exact_mad_branch(self) -> None:
        odd = self.candidate(baseline_input("odd", (1, 2, 100), (4, 5, 6), floor=0.1))
        self.assertEqual((odd.pre_median, odd.post_median, odd.pre_mad), (2.0, 5.0, 1.0))
        self.assertEqual(odd.scale, 1.4826)
        even = self.candidate(baseline_input("even", (1, 3), (5, 9), floor=1.0))
        self.assertEqual((even.pre_median, even.post_median), (2.0, 7.0))

    def test_absolute_relative_zero_and_negative_floor_branches(self) -> None:
        absolute = self.candidate(baseline_input("absolute", (1, 1), (5, 5), floor=2.0))
        self.assertEqual(absolute.scale, 2.0)
        relative = self.candidate(
            baseline_input("relative", (100, 100), (110, 110), floor=1.0),
            policy(relative=0.2),
        )
        self.assertEqual(relative.scale, 20.0)
        zero = self.candidate(
            baseline_input("zero", (0, 0), (1, 1), floor=2.0),
            policy(relative=0.5),
        )
        self.assertEqual(zero.scale, 2.0)
        negative = self.candidate(
            baseline_input("negative", (-100, -100), (-90, -90), floor=1.0),
            policy(relative=0.2),
        )
        self.assertEqual(negative.scale, 20.0)

    def test_signed_direction_and_equal_medians(self) -> None:
        positive = self.candidate(baseline_input("positive", (1, 1), (3, 3)))
        negative = self.candidate(baseline_input("negative", (3, 3), (1, 1)))
        equal = self.candidate(baseline_input("equal", (2, 2), (2, 2)))
        self.assertGreater(positive.signed_score, 0)
        self.assertLess(negative.signed_score, 0)
        self.assertEqual(positive.suspicion_score, negative.suspicion_score)
        self.assertEqual(equal.suspicion_score, 0.0)

    def test_window_boundaries_and_all_points_are_used(self) -> None:
        item = SignalBaselineInput(
            signal(
                "bounded",
                ((-1, 999), (0, 0), (1, 0), (10, 10), (11, 10), (20, 999)),
            ),
            1.0,
        )
        candidate = self.candidate(item)
        self.assertEqual((candidate.pre_point_count, candidate.post_point_count), (2, 2))
        self.assertEqual((candidate.pre_median, candidate.post_median), (0.0, 10.0))

    def test_arithmetic_overflow_is_typed(self) -> None:
        item = baseline_input("overflow", (-1e308, -1e308), (1e308, 1e308))
        with self.assertRaises(BaselineComputationError) as caught:
            rank_metric_shifts(window(), (item,), policy())
        self.assertEqual(caught.exception.code, "baseline_computation_failed")


class BaselineDecisionTests(unittest.TestCase):
    def test_eligibility_and_insufficient_abstention(self) -> None:
        for item in (
            baseline_input("pre-short", (1,), (2, 2)),
            baseline_input("post-short", (1, 1), (2,)),
        ):
            result = rank_metric_shifts(window(), (item,), policy(count=2))
            self.assertEqual(result.reason, AbstentionReason.INSUFFICIENT_EVIDENCE)  # type: ignore[union-attr]
        eligible = rank_metric_shifts(
            window(), (baseline_input("exact", (1, 1), (2, 2)),), policy(count=2)
        )
        self.assertIsInstance(eligible, BaselineRanking)
        empty = rank_metric_shifts(window(), (), policy())
        self.assertEqual(empty.reason, AbstentionReason.INSUFFICIENT_EVIDENCE)  # type: ignore[union-attr]

    def test_every_result_replays_all_signal_floors_counts_and_eligibility(self) -> None:
        empty = rank_metric_shifts(window(), (), policy())
        self.assertIsInstance(empty, BaselineAbstention)
        assert isinstance(empty, BaselineAbstention)
        self.assertEqual(empty.signal_evaluations, ())

        insufficient = rank_metric_shifts(
            window(),
            (baseline_input("short", (1,), (2, 2), floor=2.5),),
            policy(count=2),
        )
        self.assertIsInstance(insufficient, BaselineAbstention)
        assert isinstance(insufficient, BaselineAbstention)
        self.assertEqual(len(insufficient.signal_evaluations), 1)
        replay = insufficient.signal_evaluations[0]
        self.assertEqual(replay.signal_key, SignalKey("short"))
        self.assertEqual(replay.absolute_scale_floor, 2.5)
        self.assertEqual((replay.pre_point_count, replay.post_point_count), (1, 2))
        self.assertFalse(replay.eligible)
        self.assertIsNone(replay.candidate)

        mixed = rank_metric_shifts(
            window(),
            (
                baseline_input("short", (1,), (9, 9), floor=3.0),
                baseline_input("eligible", (1, 1), (4, 4), floor=0.5),
            ),
            policy(),
        )
        self.assertIsInstance(mixed, BaselineRanking)
        assert isinstance(mixed, BaselineRanking)
        self.assertEqual(
            tuple(item.signal_key.value for item in mixed.signal_evaluations),
            ("eligible", "short"),
        )
        self.assertEqual(
            tuple(item.absolute_scale_floor for item in mixed.signal_evaluations),
            (0.5, 3.0),
        )
        self.assertEqual(
            tuple(item.eligible for item in mixed.signal_evaluations),
            (True, False),
        )

    def test_mixed_eligibility_ranks_only_eligible_signal(self) -> None:
        result = rank_metric_shifts(
            window(),
            (
                baseline_input("short", (1,), (9, 9)),
                baseline_input("eligible", (1, 1), (4, 4)),
            ),
            policy(),
        )
        self.assertIsInstance(result, BaselineRanking)
        assert isinstance(result, BaselineRanking)
        self.assertEqual([item.signal_key.value for item in result.candidates], ["eligible"])

    def test_shift_ranking_is_permutation_invariant_and_ties_are_canonical(self) -> None:
        inputs = (
            baseline_input("z", (0, 0), (3, 3)),
            baseline_input("a", (0, 0), (3, 3)),
            baseline_input("middle", (0, 0), (2, 2)),
        )
        expected = rank_metric_shifts(window(), inputs, policy())
        for permutation in itertools.permutations(inputs):
            self.assertEqual(rank_metric_shifts(window(), permutation, policy()), expected)
        assert isinstance(expected, BaselineRanking)
        self.assertEqual(
            [item.signal_key.value for item in expected.candidates], ["a", "z", "middle"]
        )

    def test_duplicate_keys_fail_in_every_order(self) -> None:
        inputs = (
            baseline_input("same", (0, 0), (1, 1)),
            baseline_input("same", (1, 1), (2, 2), floor=2),
        )
        for permutation in itertools.permutations(inputs):
            with self.assertRaises(DuplicateSignalError):
                rank_metric_shifts(window(), permutation, policy())

    def test_single_candidate_score_threshold_and_infinite_lead(self) -> None:
        item = baseline_input("only", (0, 0), (2, 2))
        accepted = rank_metric_shifts(window(), (item,), policy(score=2.0, margin=999))
        self.assertIsInstance(accepted, BaselineRanking)
        assert isinstance(accepted, BaselineRanking)
        self.assertTrue(math.isinf(accepted.lead))
        weak = rank_metric_shifts(window(), (item,), policy(score=2.0000000001))
        self.assertIsInstance(weak, BaselineAbstention)
        assert isinstance(weak, BaselineAbstention)
        self.assertEqual(weak.reason, AbstentionReason.WEAK_EVIDENCE)

    def test_margin_is_inclusive_and_ambiguity_is_typed(self) -> None:
        inputs = (
            baseline_input("top", (0, 0), (3, 3)),
            baseline_input("second", (0, 0), (2, 2)),
        )
        exact = rank_metric_shifts(window(), inputs, policy(margin=1.0))
        self.assertIsInstance(exact, BaselineRanking)
        ambiguous = rank_metric_shifts(window(), inputs, policy(margin=1.0000000001))
        self.assertIsInstance(ambiguous, BaselineAbstention)
        assert isinstance(ambiguous, BaselineAbstention)
        self.assertEqual(ambiguous.reason, AbstentionReason.AMBIGUOUS_EVIDENCE)
        tie_passes = rank_metric_shifts(
            window(),
            (
                baseline_input("a", (0, 0), (1, 1)),
                baseline_input("b", (0, 0), (1, 1)),
            ),
            policy(margin=0),
        )
        self.assertIsInstance(tie_passes, BaselineRanking)

    def test_weak_precedes_ambiguous_and_replay_fields_are_immutable(self) -> None:
        result = rank_metric_shifts(
            window(),
            (
                baseline_input("a", (0, 0), (0.1, 0.1)),
                baseline_input("b", (0, 0), (0.1, 0.1)),
            ),
            policy(score=1, margin=1),
        )
        self.assertIsInstance(result, BaselineAbstention)
        assert isinstance(result, BaselineAbstention)
        self.assertEqual(result.reason, AbstentionReason.WEAK_EVIDENCE)
        self.assertIsInstance(result.evaluated_candidates, tuple)
        self.assertEqual(result.evaluated_candidates[0].absolute_scale_floor, 1.0)
        self.assertEqual(result.policy.minimum_margin, 1.0)

    def test_invalid_configuration_is_rejected(self) -> None:
        invalid_policies = (
            (0, 0, 0, 0),
            (True, 0, 0, 0),
            (1, -1, 0, 0),
            (1, 0, -1, 0),
            (1, 0, 0, -1),
            (1, math.inf, 0, 0),
        )
        for args in invalid_policies:
            with self.subTest(args=args):
                with self.assertRaises(InvalidBaselineConfigurationError):
                    BaselinePolicy(*args)
        for floor in (0, -1, math.nan, math.inf):
            with self.assertRaises(InvalidBaselineConfigurationError):
                SignalBaselineInput(signal("x", ()), floor)

    def test_generator_is_consumed_once(self) -> None:
        items = (baseline_input("x", (0, 0), (2, 2)),)
        yielded = 0

        def generate() -> itertools.chain[SignalBaselineInput]:
            nonlocal yielded
            yielded += 1
            return itertools.chain(items)

        self.assertEqual(
            rank_metric_shifts(window(), generate(), policy()),
            rank_metric_shifts(window(), items, policy()),
        )
        self.assertEqual(yielded, 1)


class PublicBoundaryTests(unittest.TestCase):
    def test_public_api_is_explicit_and_has_no_causal_verdict(self) -> None:
        self.assertEqual(set(domain.__all__), {name for name in domain.__all__})
        forbidden = ("SUPPORTED", "REFUTED", "UNKNOWN", "RootCause", "confidence")
        public_text = " ".join(domain.__all__)
        self.assertTrue(all(word not in public_text for word in forbidden))
        self.assertEqual(
            tuple(inspect.signature(SignalBaselineInput).parameters),
            ("signal", "absolute_scale_floor"),
        )

    def test_sanitized_exception_text_never_echoes_raw_canary(self) -> None:
        canary = "DO_NOT_LEAK_SERVICE"
        with self.assertRaises(InvalidIdentifierError) as caught:
            TenantId(canary if False else "")
        self.assertNotIn(canary, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
