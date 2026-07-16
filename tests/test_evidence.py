from __future__ import annotations

import itertools
import math
import unittest
from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone, tzinfo

from incident_evidence_compiler.domain.baseline import (
    AbstentionReason,
    BaselineAbstention,
    BaselinePolicy,
    BaselineRanking,
    SignalBaselineInput,
    rank_metric_shifts,
)
from incident_evidence_compiler.domain.errors import InvalidEvidenceLedgerError
from incident_evidence_compiler.domain.evidence import (
    SCHEMA_VERSION,
    MetricEvidenceLedger,
    MetricShiftDecisionKind,
    compile_metric_shift_ledger,
    validate_metric_evidence_ledger,
)
from incident_evidence_compiler.domain.identifiers import (
    EvidenceId,
    IncidentId,
    RunId,
    TenantId,
)
from incident_evidence_compiler.domain.incidents import IncidentWindow
from incident_evidence_compiler.domain.metrics import MetricPoint, MetricSignal, SignalKey

BASE = datetime(2026, 1, 1, tzinfo=UTC)
KNOWN_ELIGIBLE_ID = "sha256:9a3555a030b7731e79c962b3256fbce90a59c2dc8160d2151dee8362ec519822"
KNOWN_INELIGIBLE_ID = "sha256:519a92fa6e984676a18fa363f7c69ab2b4b3487d3af48e54a5efb37efb17dbe6"


class NoOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> None:
        return None

    def dst(self, dt: datetime | None) -> None:
        return None

    def tzname(self, dt: datetime | None) -> None:
        return None


def point(minutes: int, value: float) -> MetricPoint:
    return MetricPoint(BASE + timedelta(minutes=minutes), value)


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
    signal = MetricSignal(
        SignalKey(name),
        (point(minute, value) for minute, value in values),
    )
    return SignalBaselineInput(signal, floor)


def window() -> IncidentWindow:
    return IncidentWindow(BASE, BASE + timedelta(minutes=10), BASE + timedelta(minutes=20))


def policy(
    *, count: int = 2, score: float = 1.0, margin: float = 0.5, relative: float = 0.1
) -> BaselinePolicy:
    return BaselinePolicy(count, score, margin, relative)


def forged_policy(base: BaselinePolicy, **changes: object) -> BaselinePolicy:
    forged = object.__new__(BaselinePolicy)
    for field in (
        "minimum_points_per_window",
        "minimum_score",
        "minimum_margin",
        "relative_scale_floor",
    ):
        object.__setattr__(forged, field, changes.get(field, getattr(base, field)))
    return forged


def result_for(
    *items: SignalBaselineInput,
    configured: BaselinePolicy | None = None,
) -> BaselineRanking | BaselineAbstention:
    return rank_metric_shifts(window(), items, configured or policy())


def compile_result(
    result: BaselineRanking | BaselineAbstention,
    *,
    tenant: str = "tenant-01",
    incident: str = "incident-01",
    run: str = "run-01",
    incident_window: IncidentWindow | None = None,
) -> MetricEvidenceLedger:
    return compile_metric_shift_ledger(
        TenantId(tenant),
        IncidentId(incident),
        RunId(run),
        incident_window or window(),
        result,
    )


def known_result() -> BaselineRanking:
    result = result_for(
        baseline_input("z-short", (1.0,), (4.0, 4.0), floor=2.0),
        baseline_input("A-eligible", (1.0, 1.0), (3.0, 3.0)),
    )
    assert isinstance(result, BaselineRanking)
    return result


class LedgerCompilationTests(unittest.TestCase):
    def test_compiles_one_canonically_ordered_entry_per_evaluation(self) -> None:
        ledger = compile_result(known_result())
        self.assertEqual(ledger.schema_version, "metric-evidence-ledger.v1")
        self.assertEqual(SCHEMA_VERSION, ledger.schema_version)
        self.assertEqual(
            tuple(entry.signal_key.value for entry in ledger.entries),
            ("A-eligible", "z-short"),
        )
        eligible, ineligible = ledger.entries
        self.assertTrue(eligible.eligible)
        self.assertIsNotNone(eligible.candidate)
        self.assertEqual((eligible.pre_point_count, eligible.post_point_count), (2, 2))
        self.assertEqual(eligible.relative_scale_floor, ledger.policy.relative_scale_floor)
        self.assertFalse(ineligible.eligible)
        self.assertIsNone(ineligible.candidate)
        self.assertEqual((ineligible.pre_point_count, ineligible.post_point_count), (1, 2))
        self.assertEqual(ineligible.absolute_scale_floor, 2.0)

    def test_empty_ledger_is_valid_and_records_insufficient_abstention(self) -> None:
        result = result_for()
        self.assertIsInstance(result, BaselineAbstention)
        ledger = compile_result(result)
        self.assertEqual(ledger.entries, ())
        self.assertEqual(ledger.decision.kind, MetricShiftDecisionKind.ABSTENTION)
        self.assertEqual(ledger.decision.abstention_reason, AbstentionReason.INSUFFICIENT_EVIDENCE)
        self.assertEqual(ledger.decision.candidate_signal_keys, ())
        self.assertEqual(ledger.decision.eligible_signal_count, 0)
        self.assertIsNone(ledger.decision.top_score)

    def test_ledger_is_deeply_immutable_and_defensively_copied(self) -> None:
        source = known_result()
        ledger = compile_result(source)
        self.assertIsInstance(ledger.entries, tuple)
        self.assertIsInstance(ledger.decision.candidate_signal_keys, tuple)
        mutations: tuple[Callable[[], None], ...] = (
            lambda: setattr(ledger, "schema_version", "forged"),
            lambda: setattr(ledger.entries[0], "eligible", False),
            lambda: setattr(ledger.policy, "minimum_score", 0.0),
            lambda: setattr(ledger.window, "end", BASE),
            lambda: setattr(ledger.decision, "lead", 0.0),
            lambda: setattr(ledger.entries[0].candidate, "signed_score", 0.0),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.assertRaises(FrozenInstanceError):
                    mutation()
        self.assertIsNot(ledger.policy, source.policy)
        self.assertIsNot(ledger.entries[0].candidate, source.candidates[0])

    def test_window_is_normalized_to_utc(self) -> None:
        offset = timezone(timedelta(hours=5, minutes=30))
        shifted = IncidentWindow(
            datetime(2026, 1, 1, 5, 30, tzinfo=offset),
            datetime(2026, 1, 1, 5, 40, tzinfo=offset),
            datetime(2026, 1, 1, 5, 50, tzinfo=offset),
        )
        ledger = compile_result(known_result(), incident_window=shifted)
        self.assertIs(ledger.window.start.tzinfo, UTC)
        self.assertEqual(ledger.window, window())

    def test_repr_is_bounded_and_does_not_expose_canaries(self) -> None:
        canaries = ("tenant-01", "incident-01", "run-01", "A-eligible", "sha256:")
        ledger = compile_result(known_result())
        representations = (
            repr(ledger),
            repr(ledger.decision),
            *(repr(item) for item in ledger.entries),
        )
        for representation in representations:
            with self.subTest(representation=representation):
                self.assertLess(len(representation), 150)
                self.assertTrue(all(canary not in representation for canary in canaries))
        self.assertIn("entry_count=2", repr(ledger))
        self.assertIn("candidate_count=1", repr(ledger.decision))


class DeterministicEvidenceIdTests(unittest.TestCase):
    def test_ids_match_fixed_known_vectors(self) -> None:
        ledger = compile_result(known_result())
        self.assertEqual(ledger.entries[0].evidence_id.value, KNOWN_ELIGIBLE_ID)
        self.assertEqual(ledger.entries[1].evidence_id.value, KNOWN_INELIGIBLE_ID)
        for entry in ledger.entries:
            prefix, digest = entry.evidence_id.value.split(":", 1)
            self.assertEqual(prefix, "sha256")
            self.assertEqual(len(digest), 64)
            self.assertEqual(digest, digest.lower())

    def test_ids_are_invariant_to_input_and_evaluation_order(self) -> None:
        items = (
            baseline_input("z-short", (1.0,), (4.0, 4.0), floor=2.0),
            baseline_input("A-eligible", (1.0, 1.0), (3.0, 3.0)),
        )
        expected = tuple(entry.evidence_id for entry in compile_result(result_for(*items)).entries)
        for permutation in itertools.permutations(items):
            result = result_for(*permutation)
            reversed_evaluations = replace(
                result,
                signal_evaluations=tuple(reversed(result.signal_evaluations)),
            )
            self.assertEqual(
                tuple(entry.evidence_id for entry in compile_result(reversed_evaluations).entries),
                expected,
            )

    def test_every_committed_binding_window_policy_decision_and_entry_field_changes_id(
        self,
    ) -> None:
        original_result = known_result()
        original = compile_result(original_result).entries[0].evidence_id
        changed_ledgers = (
            compile_result(original_result, tenant="tenant-02"),
            compile_result(original_result, incident="incident-02"),
            compile_result(original_result, run="run-02"),
            compile_result(
                original_result,
                incident_window=IncidentWindow(
                    BASE - timedelta(microseconds=1),
                    window().injection,
                    window().end,
                ),
            ),
            compile_result(
                result_for(
                    baseline_input("z-short", (1.0,), (4.0, 4.0), floor=2.0),
                    baseline_input("A-eligible", (1.0, 1.0), (3.0, 3.0)),
                    configured=policy(score=1.5),
                )
            ),
            compile_result(
                result_for(
                    baseline_input("z-short", (1.0,), (4.0, 4.0), floor=2.0),
                    baseline_input("A-eligible", (1.0, 1.0), (4.0, 4.0)),
                )
            ),
        )
        for ledger in changed_ledgers:
            with self.subTest(ledger=repr(ledger)):
                self.assertNotEqual(ledger.entries[0].evidence_id, original)

    def test_unicode_identifiers_are_content_bound_without_ascii_loss(self) -> None:
        first = compile_result(known_result(), tenant="租户").entries[0].evidence_id
        second = compile_result(known_result(), tenant="tenant").entries[0].evidence_id
        self.assertNotEqual(first, second)


class BaselineInvariantTests(unittest.TestCase):
    def assert_invalid(self, result: object) -> None:
        with self.assertRaises(InvalidEvidenceLedgerError) as caught:
            compile_metric_shift_ledger(
                TenantId("DO_NOT_LEAK_TENANT"),
                IncidentId("DO_NOT_LEAK_INCIDENT"),
                RunId("DO_NOT_LEAK_RUN"),
                window(),
                result,  # type: ignore[arg-type]
            )
        self.assertEqual(str(caught.exception), "invalid_evidence_ledger")
        self.assertNotIn("DO_NOT_LEAK", str(caught.exception))

    def test_rejects_wrong_baseline_and_forged_policy(self) -> None:
        self.assert_invalid(object())
        baseline = known_result()
        forged_policies = (
            forged_policy(baseline.policy, minimum_points_per_window=0),
            forged_policy(baseline.policy, minimum_points_per_window=True),
            forged_policy(baseline.policy, minimum_score=math.nan),
            forged_policy(baseline.policy, minimum_margin=-1.0),
            forged_policy(baseline.policy, relative_scale_floor=math.inf),
        )
        for forged in forged_policies:
            with self.subTest(forged=type(forged)):
                self.assert_invalid(replace(baseline, policy=forged))

    def test_rejects_duplicate_keys_and_invalid_evaluation_shapes(self) -> None:
        baseline = known_result()
        eligible = baseline.signal_evaluations[0]
        ineligible = baseline.signal_evaluations[1]
        malformed = (
            replace(baseline, signal_evaluations=(eligible, eligible)),
            replace(baseline, signal_evaluations=[eligible]),  # type: ignore[arg-type]
            replace(baseline, signal_evaluations=(object(),)),  # type: ignore[arg-type]
            replace(baseline, signal_evaluations=(replace(eligible, eligible=False), ineligible)),
            replace(baseline, signal_evaluations=(replace(ineligible, eligible=True), eligible)),
            replace(baseline, signal_evaluations=(replace(eligible, candidate=None), ineligible)),
            replace(
                baseline,
                signal_evaluations=(replace(ineligible, candidate=eligible.candidate), eligible),
            ),
            replace(
                baseline,
                signal_evaluations=(replace(eligible, absolute_scale_floor=0.0), ineligible),
            ),
            replace(
                baseline, signal_evaluations=(replace(eligible, pre_point_count=True), ineligible)
            ),
            replace(
                baseline, signal_evaluations=(replace(eligible, post_point_count=-1), ineligible)
            ),
        )
        for item in malformed:
            with self.subTest(item=type(item.signal_evaluations)):
                self.assert_invalid(item)

    def test_rejects_candidate_key_count_and_floor_disagreement(self) -> None:
        baseline = known_result()
        evaluation = baseline.signal_evaluations[0]
        assert evaluation.candidate is not None
        candidate = evaluation.candidate
        variants = (
            replace(candidate, signal_key=SignalKey("other")),
            replace(candidate, pre_point_count=candidate.pre_point_count + 1),
            replace(candidate, post_point_count=candidate.post_point_count + 1),
            replace(candidate, absolute_scale_floor=candidate.absolute_scale_floor + 1.0),
            replace(candidate, relative_scale_floor=candidate.relative_scale_floor + 1.0),
        )
        for variant in variants:
            forged_evaluation = replace(evaluation, candidate=variant)
            self.assert_invalid(
                replace(
                    baseline,
                    signal_evaluations=(forged_evaluation, baseline.signal_evaluations[1]),
                    candidates=(variant,),
                )
            )

    def test_rejects_every_nonfinite_replay_field(self) -> None:
        baseline = known_result()
        evaluation = baseline.signal_evaluations[0]
        assert evaluation.candidate is not None
        float_fields = (
            "pre_median",
            "post_median",
            "pre_mad",
            "absolute_scale_floor",
            "relative_scale_floor",
            "scale",
            "signed_score",
            "suspicion_score",
        )
        for field, value in itertools.product(float_fields, (math.nan, math.inf, -math.inf)):
            with self.subTest(field=field, value=value):
                candidate = replace(
                    evaluation.candidate,
                    **{field: value},  # type: ignore[arg-type]
                )
                forged_evaluation = replace(evaluation, candidate=candidate)
                self.assert_invalid(
                    replace(
                        baseline,
                        signal_evaluations=(forged_evaluation, baseline.signal_evaluations[1]),
                        candidates=(candidate,),
                    )
                )

    def test_rejects_negative_or_formula_inconsistent_replay_values(self) -> None:
        baseline = known_result()
        evaluation = baseline.signal_evaluations[0]
        assert evaluation.candidate is not None
        candidate = evaluation.candidate
        variants = (
            replace(candidate, pre_mad=-1.0),
            replace(candidate, absolute_scale_floor=0.0),
            replace(candidate, relative_scale_floor=-0.1),
            replace(candidate, scale=0.0),
            replace(candidate, scale=candidate.scale + 1.0),
            replace(candidate, signed_score=candidate.signed_score + 1.0),
            replace(candidate, suspicion_score=candidate.suspicion_score + 1.0),
            replace(candidate, post_median=candidate.post_median + 1.0),
        )
        for variant in variants:
            forged_evaluation = replace(evaluation, candidate=variant)
            self.assert_invalid(
                replace(
                    baseline,
                    signal_evaluations=(forged_evaluation, baseline.signal_evaluations[1]),
                    candidates=(variant,),
                )
            )

    def test_rejects_forged_ranking_fields_and_order(self) -> None:
        baseline = result_for(
            baseline_input("high", (0.0, 0.0), (3.0, 3.0)),
            baseline_input("low", (0.0, 0.0), (1.0, 1.0)),
            configured=policy(margin=1.0),
        )
        self.assertIsInstance(baseline, BaselineRanking)
        assert isinstance(baseline, BaselineRanking)
        malformed = (
            replace(baseline, candidates=tuple(reversed(baseline.candidates))),
            replace(baseline, candidates=baseline.candidates[:1]),
            replace(baseline, lead=baseline.lead + 1.0),
            replace(baseline, lead=math.nan),
            replace(baseline, policy=replace(baseline.policy, minimum_score=4.0)),
            replace(baseline, policy=replace(baseline.policy, minimum_margin=3.0)),
        )
        for item in malformed:
            self.assert_invalid(item)

    def test_rejects_forged_single_ranking_lead(self) -> None:
        baseline = known_result()
        for lead in (0.0, 1.0, math.nan, -math.inf):
            with self.subTest(lead=lead):
                self.assert_invalid(replace(baseline, lead=lead))

    def test_rejects_forged_abstention_fields_and_precedence(self) -> None:
        insufficient = result_for()
        weak = result_for(
            baseline_input("weak", (0.0, 0.0), (0.5, 0.5)),
            configured=policy(score=1.0),
        )
        ambiguous = result_for(
            baseline_input("a", (0.0, 0.0), (2.0, 2.0)),
            baseline_input("b", (0.0, 0.0), (2.0, 2.0)),
            configured=policy(margin=0.1),
        )
        self.assertIsInstance(insufficient, BaselineAbstention)
        self.assertIsInstance(weak, BaselineAbstention)
        self.assertIsInstance(ambiguous, BaselineAbstention)
        assert isinstance(insufficient, BaselineAbstention)
        assert isinstance(weak, BaselineAbstention)
        assert isinstance(ambiguous, BaselineAbstention)
        malformed = (
            replace(insufficient, reason=AbstentionReason.WEAK_EVIDENCE),
            replace(insufficient, eligible_signal_count=1),
            replace(insufficient, top_score=0.0),
            replace(weak, reason=AbstentionReason.AMBIGUOUS_EVIDENCE),
            replace(weak, top_score=weak.top_score + 1.0 if weak.top_score is not None else 1.0),
            replace(weak, evaluated_candidates=()),
            replace(ambiguous, reason=AbstentionReason.WEAK_EVIDENCE),
            replace(ambiguous, second_score=None),
            replace(ambiguous, eligible_signal_count=1),
            replace(ambiguous, policy=replace(ambiguous.policy, minimum_margin=0.0)),
        )
        for item in malformed:
            self.assert_invalid(item)

    def test_rejects_forged_window_without_usable_offset(self) -> None:
        forged = object.__new__(IncidentWindow)
        object.__setattr__(forged, "start", datetime(2026, 1, 1, tzinfo=NoOffset()))
        object.__setattr__(forged, "injection", datetime(2026, 1, 1, 0, 1, tzinfo=NoOffset()))
        object.__setattr__(forged, "end", datetime(2026, 1, 1, 0, 2, tzinfo=NoOffset()))
        with self.assertRaises(InvalidEvidenceLedgerError):
            compile_metric_shift_ledger(
                TenantId("tenant"),
                IncidentId("incident"),
                RunId("run"),
                forged,
                known_result(),
            )

    def test_rejects_invalid_bindings_and_window_without_echoing_them(self) -> None:
        baseline = known_result()
        calls = (
            (object(), IncidentId("incident"), RunId("run"), window()),
            (TenantId("tenant"), object(), RunId("run"), window()),
            (TenantId("tenant"), IncidentId("incident"), object(), window()),
            (TenantId("tenant"), IncidentId("incident"), RunId("run"), object()),
        )
        for tenant, incident, run, incident_window in calls:
            with self.assertRaises(InvalidEvidenceLedgerError) as caught:
                compile_metric_shift_ledger(
                    tenant,  # type: ignore[arg-type]
                    incident,  # type: ignore[arg-type]
                    run,  # type: ignore[arg-type]
                    incident_window,  # type: ignore[arg-type]
                    baseline,
                )
            self.assertEqual(str(caught.exception), "invalid_evidence_ledger")


class ExplodingOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta:
        raise RuntimeError("TIMEZONE_SECRET")

    def dst(self, dt: datetime | None) -> timedelta:
        raise RuntimeError("TIMEZONE_SECRET")

    def tzname(self, dt: datetime | None) -> str:
        raise RuntimeError("TIMEZONE_SECRET")


class FullLedgerValidationTests(unittest.TestCase):
    def assert_stable_failure(self, ledger: object) -> None:
        with self.assertRaises(InvalidEvidenceLedgerError) as caught:
            validate_metric_evidence_ledger(ledger)
        self.assertEqual(str(caught.exception), "invalid_evidence_ledger")
        self.assertNotIn("SECRET", str(caught.exception))

    def test_rejects_structurally_valid_but_stale_evidence_id(self) -> None:
        ledger = compile_result(known_result())
        stale_entry = replace(ledger.entries[0], evidence_id=EvidenceId("sha256:" + "0" * 64))
        self.assert_stable_failure(replace(ledger, entries=(stale_entry, ledger.entries[1])))

    def test_rejects_invalid_window_and_decision_state(self) -> None:
        ledger = compile_result(known_result())
        forged_window = object.__new__(IncidentWindow)
        object.__setattr__(forged_window, "start", ledger.window.end)
        object.__setattr__(forged_window, "injection", ledger.window.injection)
        object.__setattr__(forged_window, "end", ledger.window.start)
        self.assert_stable_failure(replace(ledger, window=forged_window))

        forged_decision = replace(
            ledger.decision,
            kind="ranking",  # type: ignore[arg-type]
        )
        self.assert_stable_failure(replace(ledger, decision=forged_decision))
        self.assert_stable_failure(
            replace(ledger, decision=replace(ledger.decision, top_score=99.0))
        )

    def test_unicode_and_timezone_failures_are_sanitized(self) -> None:
        with self.assertRaises(InvalidEvidenceLedgerError) as unicode_error:
            compile_result(known_result(), tenant="bad\ud800tenant")
        self.assertEqual(str(unicode_error.exception), "invalid_evidence_ledger")

        forged_window = object.__new__(IncidentWindow)
        hostile = datetime(2026, 1, 1, tzinfo=ExplodingOffset())
        object.__setattr__(forged_window, "start", hostile)
        object.__setattr__(forged_window, "injection", hostile)
        object.__setattr__(forged_window, "end", hostile)
        self.assert_stable_failure(replace(compile_result(known_result()), window=forged_window))


class ReviewBoundaryRegressionTests(unittest.TestCase):
    def test_malformed_exact_baseline_instances_are_sanitized(self) -> None:
        for baseline_type in (BaselineRanking, BaselineAbstention):
            with self.subTest(baseline_type=baseline_type.__name__):
                malformed = object.__new__(baseline_type)
                with self.assertRaises(InvalidEvidenceLedgerError) as caught:
                    compile_metric_shift_ledger(
                        TenantId("tenant"),
                        IncidentId("incident"),
                        RunId("run"),
                        window(),
                        malformed,  # type: ignore[arg-type]
                    )
                self.assertEqual(str(caught.exception), "invalid_evidence_ledger")


if __name__ == "__main__":
    unittest.main()
