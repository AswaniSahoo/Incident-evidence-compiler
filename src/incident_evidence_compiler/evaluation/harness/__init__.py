"""Label-safe evaluation harness for the RCAEval RE2 development split.

This package scores the deterministic baseline (and, optionally, a
verifier-gated LLM arm) against ground-truth root-cause labels. The ground truth
lives only in the evaluation ``EvaluationSidecar`` and is consumed only here, in
the evaluation layer; it is never passed to investigation code. The harness
depends on ``domain`` and ``llm`` but not on ``application`` or ``persistence``,
and performs no network or database I/O.
"""

from .baseline_inputs import (
    DEFAULT_ABSOLUTE_EPSILON,
    DEFAULT_EVALUATION_POLICY,
    DEFAULT_RELATIVE_FLOOR_FRACTION,
    ScaleFloorPolicy,
    service_of,
    to_baseline_inputs,
)
from .runner import (
    Arm,
    evaluate_batch,
    predict_services_baseline,
    predict_services_with_llm,
)
from .scoring import (
    CaseScore,
    EvaluationSummary,
    aggregate,
    score_case,
    summary_json,
)

__all__ = [
    "DEFAULT_ABSOLUTE_EPSILON",
    "DEFAULT_EVALUATION_POLICY",
    "DEFAULT_RELATIVE_FLOOR_FRACTION",
    "Arm",
    "CaseScore",
    "EvaluationSummary",
    "ScaleFloorPolicy",
    "aggregate",
    "evaluate_batch",
    "predict_services_baseline",
    "predict_services_with_llm",
    "score_case",
    "service_of",
    "summary_json",
    "to_baseline_inputs",
]
