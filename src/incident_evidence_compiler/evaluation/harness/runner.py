"""Run an evaluation arm over an adapter-loaded batch and score it.

Two arms are supported:

* **baseline**, deterministic, no network: rank metric shifts and predict the
  services of the ranked candidate signals.
* **gemini**, the full restricted-hypothesis pipeline: compile the evidence
  ledger, ask an ``LLMClient`` for hypotheses over the allow-listed signals, parse
  the untrusted output, verify it deterministically, and predict the services of
  the signals the verifier ``SUPPORTED`` (ranked by baseline suspicion). Any
  untrusted-output or provider failure yields no verified conclusion and is scored
  as an abstention for that case.

The arm receives only investigation-safe inputs; ground-truth services come from
the sidecar and are joined to predictions here for scoring only.
"""

import asyncio
from collections.abc import Iterable
from enum import StrEnum

from ...domain import (
    BaselineAbstention,
    BaselinePolicy,
    IncidentId,
    RunId,
    TenantId,
    compile_metric_shift_ledger,
    rank_metric_shifts,
    verify_hypothesis,
)
from ...llm import (
    HypothesisRequest,
    LLMClient,
    LLMError,
    LLMValidationError,
    parse_metric_hypothesis,
)
from ..rcaeval import EvaluationBatch, InvestigationCase
from .baseline_inputs import (
    DEFAULT_EVALUATION_POLICY,
    ScaleFloorPolicy,
    service_of,
    to_baseline_inputs,
)
from .scoring import EvaluationSummary, aggregate, score_case

# A fixed, opaque tenant for evaluation runs; the incident/run identifiers are the
# case's random UUID, which carries no source locator or label.
_EVALUATION_TENANT = TenantId("evaluation")

# Transient provider-failure retry policy for the evaluation LLM arm (rate limits etc.),
# so infrastructure noise does not masquerade as the model declining to support a claim.
_MAX_PROVIDER_RETRIES = 5
_PROVIDER_BACKOFF_SECONDS = 1.0


class Arm(StrEnum):
    """The evaluation arm to run."""

    BASELINE = "baseline"
    GEMINI = "gemini"


def _context(case: InvestigationCase) -> tuple[TenantId, IncidentId, RunId]:
    case_ref = str(case.case_id)
    return _EVALUATION_TENANT, IncidentId(case_ref), RunId(case_ref)


def _dedup(services: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for service in services:
        if service not in seen:
            seen.add(service)
            ordered.append(service)
    return tuple(ordered)


def predict_services_baseline(
    case: InvestigationCase,
    *,
    policy: BaselinePolicy = DEFAULT_EVALUATION_POLICY,
    floor_policy: ScaleFloorPolicy | None = None,
) -> tuple[tuple[str, ...], bool]:
    """Return ``(ranked_services, abstained)`` from the deterministic baseline."""
    inputs = to_baseline_inputs(case.signals, floor_policy=floor_policy)
    result = rank_metric_shifts(case.window, inputs, policy)
    if isinstance(result, BaselineAbstention):
        return (), True
    services = _dedup(service_of(candidate.signal_key.value) for candidate in result.candidates)
    return services, False


async def predict_services_with_llm(
    case: InvestigationCase,
    llm_client: LLMClient,
    *,
    policy: BaselinePolicy = DEFAULT_EVALUATION_POLICY,
    floor_policy: ScaleFloorPolicy | None = None,
) -> tuple[tuple[str, ...], bool, int]:
    """Return ``(ranked_services, abstained, invalid_evidence_id_count)`` for the LLM arm."""
    inputs = to_baseline_inputs(case.signals, floor_policy=floor_policy)
    baseline = rank_metric_shifts(case.window, inputs, policy)
    tenant, incident, run = _context(case)
    ledger = compile_metric_shift_ledger(tenant, incident, run, case.window, baseline)
    allowed = frozenset(entry.signal_key for entry in ledger.entries)
    request = HypothesisRequest(tenant=tenant, incident=incident, run=run, allowed_signals=allowed)
    # Retry transient provider failures (e.g. rate limits) with backoff so infrastructure
    # noise is not miscounted as the model declining to support a hypothesis. Only an
    # invalid/untrusted model output (LLMValidationError) or exhausted retries score as an
    # abstention for this case.
    proposal = None
    for attempt in range(_MAX_PROVIDER_RETRIES + 1):
        try:
            proposal = await llm_client.propose_metric_hypotheses(request)
            break
        except LLMValidationError:
            return (), True, 0
        except LLMError:
            if attempt >= _MAX_PROVIDER_RETRIES:
                return (), True, 0
            await asyncio.sleep(_PROVIDER_BACKOFF_SECONDS * (2**attempt))
    if proposal is None:  # pragma: no cover - defensive; loop either breaks or returns
        return (), True, 0
    try:
        document = parse_metric_hypothesis(proposal.raw_json, allowed_signals=allowed)
        verification = verify_hypothesis(document, ledger)
    except LLMError:
        # Invalid untrusted output: score as an abstention for this case.
        return (), True, 0

    entry_by_id = {entry.evidence_id: entry for entry in ledger.entries}
    suspicion = {
        entry.signal_key: (entry.candidate.suspicion_score if entry.candidate is not None else 0.0)
        for entry in ledger.entries
    }
    invalid_evidence_id_count = sum(
        1 for evidence_id in verification.supporting_evidence_ids if evidence_id not in entry_by_id
    )
    supported_keys = []
    seen: set[str] = set()
    for evidence_id in verification.supporting_evidence_ids:
        entry = entry_by_id.get(evidence_id)
        if entry is None or entry.signal_key.value in seen:
            continue
        seen.add(entry.signal_key.value)
        supported_keys.append(entry.signal_key)
    supported_keys.sort(key=lambda key: (-suspicion.get(key, 0.0), key.value))
    services = _dedup(service_of(key.value) for key in supported_keys)
    return services, not services, invalid_evidence_id_count


async def evaluate_batch(
    batch: EvaluationBatch,
    *,
    arm: Arm = Arm.BASELINE,
    policy: BaselinePolicy = DEFAULT_EVALUATION_POLICY,
    floor_policy: ScaleFloorPolicy | None = None,
    llm_client: LLMClient | None = None,
    limit: int | None = None,
    concurrency: int = 1,
) -> EvaluationSummary:
    """Score every case in a loaded batch under one arm and aggregate the metrics.

    ``limit`` (when set) scores only the first ``limit`` cases, for cheap pre-checks.
    ``concurrency`` bounds the number of in-flight provider calls on the gemini arm; the
    deterministic baseline arm ignores it. Scoring is order-independent, so concurrency
    does not affect the aggregate result.
    """
    if arm is Arm.GEMINI and llm_client is None:
        raise ValueError("the gemini arm requires an llm_client")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    ground_truth = {entry.case_id: entry.root_cause_service for entry in batch.sidecar.entries}
    cases = batch.cases if limit is None else batch.cases[:limit]

    if arm is Arm.GEMINI:
        assert llm_client is not None  # narrowed by the guard above
        semaphore = asyncio.Semaphore(concurrency)

        async def _predict(case: InvestigationCase) -> tuple[tuple[str, ...], bool, int]:
            async with semaphore:
                return await predict_services_with_llm(
                    case, llm_client, policy=policy, floor_policy=floor_policy
                )

        predictions = await asyncio.gather(*(_predict(case) for case in cases))
        scores = [
            score_case(
                services,
                ground_truth[case.case_id],
                abstained=abstained,
                invalid_evidence_id_count=invalid,
            )
            for case, (services, abstained, invalid) in zip(cases, predictions, strict=True)
        ]
        return aggregate(scores)

    scores = []
    for case in cases:
        services, abstained = predict_services_baseline(
            case, policy=policy, floor_policy=floor_policy
        )
        scores.append(score_case(services, ground_truth[case.case_id], abstained=abstained))
    return aggregate(scores)
