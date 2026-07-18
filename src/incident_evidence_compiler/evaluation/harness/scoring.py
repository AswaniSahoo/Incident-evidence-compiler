"""Label-free scoring for root-cause localization on the RCAEval RE2 dev split.

A prediction is an ordered, de-duplicated ranking of candidate services. The
ground-truth service comes from the evaluation sidecar and is compared here only.
Metrics are reported two ways for honesty: *overall* (an abstention counts as a
miss, so accuracy reflects coverage) and *answered-only* (over the cases where the
system committed to a ranking), alongside the abstention rate.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CaseScore:
    """The scored outcome for one evaluation case."""

    abstained: bool
    hit_rank: int | None
    predicted_service_count: int
    invalid_evidence_id_count: int

    @property
    def top1(self) -> bool:
        return self.hit_rank == 1

    @property
    def top3(self) -> bool:
        return self.hit_rank is not None and self.hit_rank <= 3

    @property
    def reciprocal_rank(self) -> float:
        return 0.0 if self.hit_rank is None else 1.0 / self.hit_rank


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    """Aggregate, label-free metrics over a set of case scores."""

    case_count: int
    abstained_count: int
    answered_count: int
    abstention_rate: float
    top1_accuracy: float
    top3_accuracy: float
    mrr: float
    top1_accuracy_answered: float
    top3_accuracy_answered: float
    mrr_answered: float
    invalid_evidence_id_count: int


def score_case(
    predicted_services: Sequence[str],
    ground_truth_service: str,
    *,
    abstained: bool,
    invalid_evidence_id_count: int = 0,
) -> CaseScore:
    """Score one case against its ground-truth service.

    ``predicted_services`` must already be de-duplicated in rank order. When the
    system abstained the ranking is treated as empty and the case cannot hit.
    """
    if invalid_evidence_id_count < 0:
        raise ValueError("invalid_evidence_id_count must be non-negative")
    ranking: tuple[str, ...] = () if abstained else tuple(predicted_services)
    hit_rank: int | None = None
    for index, service in enumerate(ranking, start=1):
        if service == ground_truth_service:
            hit_rank = index
            break
    return CaseScore(
        abstained=abstained,
        hit_rank=hit_rank,
        predicted_service_count=len(ranking),
        invalid_evidence_id_count=invalid_evidence_id_count,
    )


def _ratio(numerator: float, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def aggregate(scores: Sequence[CaseScore]) -> EvaluationSummary:
    """Reduce per-case scores into aggregate metrics."""
    case_count = len(scores)
    abstained_count = sum(1 for score in scores if score.abstained)
    answered_count = case_count - abstained_count
    answered = [score for score in scores if not score.abstained]
    return EvaluationSummary(
        case_count=case_count,
        abstained_count=abstained_count,
        answered_count=answered_count,
        abstention_rate=_ratio(abstained_count, case_count),
        top1_accuracy=_ratio(sum(1 for s in scores if s.top1), case_count),
        top3_accuracy=_ratio(sum(1 for s in scores if s.top3), case_count),
        mrr=_ratio(sum(s.reciprocal_rank for s in scores), case_count),
        top1_accuracy_answered=_ratio(sum(1 for s in answered if s.top1), answered_count),
        top3_accuracy_answered=_ratio(sum(1 for s in answered if s.top3), answered_count),
        mrr_answered=_ratio(sum(s.reciprocal_rank for s in answered), answered_count),
        invalid_evidence_id_count=sum(s.invalid_evidence_id_count for s in scores),
    )


def summary_payload(summary: EvaluationSummary) -> dict[str, object]:
    """A JSON-ready mapping of the summary; floats rounded for stable artifacts."""
    return {
        "case_count": summary.case_count,
        "abstained_count": summary.abstained_count,
        "answered_count": summary.answered_count,
        "abstention_rate": round(summary.abstention_rate, 6),
        "top1_accuracy": round(summary.top1_accuracy, 6),
        "top3_accuracy": round(summary.top3_accuracy, 6),
        "mrr": round(summary.mrr, 6),
        "top1_accuracy_answered": round(summary.top1_accuracy_answered, 6),
        "top3_accuracy_answered": round(summary.top3_accuracy_answered, 6),
        "mrr_answered": round(summary.mrr_answered, 6),
        "invalid_evidence_id_count": summary.invalid_evidence_id_count,
    }


def summary_json(summary: EvaluationSummary) -> str:
    """Canonical JSON for one aggregate summary."""
    return json.dumps(summary_payload(summary), sort_keys=True, separators=(",", ":")) + "\n"
