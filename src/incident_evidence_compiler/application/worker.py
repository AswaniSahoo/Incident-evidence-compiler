"""The investigation worker.

Claims one queued job per ``run_once`` and runs the pipeline in a single unit of work:
set RUNNING, load telemetry, compute the baseline, compile the evidence ledger, ask the
LLM for restricted hypotheses, parse the untrusted output, verify deterministically, then
persist one content-addressed evidence row per ledger entry and one verification report.

Failure handling is typed and leakage-safe: untrusted-output and domain failures are
terminal (the investigation is FAILED and only a stable ``error_code`` is recorded, never
model text); provider timeouts/unavailability are retried up to ``max_attempts`` and then
terminal. The external LLM call is bounded by a per-attempt deadline so a stalled model
cannot wedge the loop.
"""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from ..domain import (
    EVIDENCE_SCHEMA_VERSION,
    VERIFICATION_SCHEMA_VERSION,
    BaselinePolicy,
    DomainError,
    compile_metric_shift_ledger,
    metric_evidence_entry_json,
    rank_metric_shifts,
    verification_json,
    verify_hypothesis,
)
from ..llm import (
    HypothesisRequest,
    LLMClient,
    LLMValidationError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    parse_metric_hypothesis,
)
from ..observability import MetricsRegistry
from ..persistence import (
    AttemptId,
    AttemptOutcome,
    AttemptRecord,
    AuditRecord,
    ClaimedJob,
    EvidenceRecord,
    InvestigationRecord,
    InvestigationStatus,
    JobStatus,
    LedgerKind,
    RecordNotFoundError,
    ReportRecord,
    UnitOfWork,
    UnitOfWorkFactory,
)
from .errors import TelemetryUnavailableError
from .telemetry import TelemetrySource

DEFAULT_BASELINE_POLICY = BaselinePolicy(
    minimum_points_per_window=2,
    minimum_score=1.0,
    minimum_margin=0.0,
    relative_scale_floor=0.0,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _TerminalFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _RetryableFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Worker:
    """Runs queued investigation jobs to a persisted verification report."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        llm_client: LLMClient,
        telemetry: TelemetrySource,
        *,
        worker_id: str,
        lease: timedelta = timedelta(seconds=30),
        deadline: timedelta = timedelta(seconds=30),
        max_attempts: int = 3,
        policy: BaselinePolicy = DEFAULT_BASELINE_POLICY,
        clock: Callable[[], datetime] = _utcnow,
        id_factory: Callable[[], UUID] = uuid4,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id must be non-empty")
        self._uow_factory = uow_factory
        self._llm = llm_client
        self._telemetry = telemetry
        self._worker_id = worker_id
        self._lease = lease
        self._deadline = deadline
        self._max_attempts = max_attempts
        self._policy = policy
        self._clock = clock
        self._id_factory = id_factory
        # A shared registry lets a co-located /metrics endpoint expose these; an unshared
        # default keeps the worker fully functional when metrics are not scraped.
        self._metrics = metrics if metrics is not None else MetricsRegistry()
        self._jobs_total = self._metrics.counter(
            "iec_worker_jobs_total", "Worker job outcomes.", ("outcome",)
        )
        self._stage_seconds = self._metrics.histogram(
            "iec_worker_stage_duration_seconds",
            "Per-stage worker latency in seconds.",
            labelnames=("stage",),
        )
        self._provider_timeouts_total = self._metrics.counter(
            "iec_provider_timeouts_total", "LLM provider timeouts."
        )
        self._llm_tokens_total = self._metrics.counter(
            "iec_llm_tokens_total", "LLM tokens consumed.", ("kind",)
        )
        self._verdicts_total = self._metrics.counter(
            "iec_investigation_verdicts_total", "Verification verdicts.", ("verdict",)
        )

    async def run_once(self) -> bool:
        """Claim and process one job. Return False if the queue had no eligible job."""
        async with self._uow_factory() as uow:
            claimed = await uow.jobs.claim(self._worker_id, lease=self._lease, now=self._clock())
            if claimed is None:
                await uow.commit()
                return False
            started = self._clock()
            try:
                investigation = await uow.investigations.get(
                    claimed.tenant, claimed.investigation_id
                )
            except RecordNotFoundError:
                await uow.jobs.set_status(claimed.tenant, claimed.job_id, JobStatus.FAILED)
                await uow.commit()
                return True

            if investigation.status == InvestigationStatus.CANCELLED:
                await uow.jobs.set_status(claimed.tenant, claimed.job_id, JobStatus.CANCELLED)
                self._jobs_total.inc(labels=("cancelled",))
                await uow.commit()
                return True

            await uow.investigations.set_status(
                claimed.tenant, claimed.investigation_id, InvestigationStatus.RUNNING
            )
            try:
                await self._run_pipeline(uow, investigation)
            except _TerminalFailure as failure:
                await self._terminal_fail(uow, claimed, started, failure.code)
            except _RetryableFailure as failure:
                await self._retry_or_fail(uow, claimed, started, failure.code)
            else:
                await uow.jobs.set_status(claimed.tenant, claimed.job_id, JobStatus.SUCCEEDED)
                await self._record_attempt(uow, claimed, started, AttemptOutcome.SUCCEEDED, None)
                self._jobs_total.inc(labels=("succeeded",))
            await uow.commit()
            return True

    async def _run_pipeline(self, uow: UnitOfWork, investigation: InvestigationRecord) -> None:
        try:
            with self._stage_seconds.time(labels=("telemetry_load",)):
                telemetry = await self._telemetry.load(
                    investigation.tenant, investigation.incident, investigation.run
                )
        except TelemetryUnavailableError:
            raise _TerminalFailure("telemetry_unavailable") from None

        try:
            with self._stage_seconds.time(labels=("baseline",)):
                baseline = rank_metric_shifts(investigation.window, telemetry, self._policy)
                ledger = compile_metric_shift_ledger(
                    investigation.tenant,
                    investigation.incident,
                    investigation.run,
                    investigation.window,
                    baseline,
                )
        except DomainError as exc:
            raise _TerminalFailure(exc.code) from None

        allowed = frozenset(entry.signal_key for entry in ledger.entries)
        request = HypothesisRequest(
            tenant=investigation.tenant,
            incident=investigation.incident,
            run=investigation.run,
            allowed_signals=allowed,
        )

        try:
            with self._stage_seconds.time(labels=("llm_propose",)):
                async with asyncio.timeout(self._deadline.total_seconds()):
                    proposal = await self._llm.propose_metric_hypotheses(request)
        except TimeoutError:
            self._provider_timeouts_total.inc()
            raise _RetryableFailure("provider_timeout") from None
        except (ProviderTimeoutError, ProviderUnavailableError):
            raise _RetryableFailure("provider_unavailable") from None
        except ProviderResponseError:
            raise _TerminalFailure("provider_response_invalid") from None

        # Token counts are untrusted provider metadata; only record strictly positive
        # values so a hostile or malformed non-positive count cannot raise inside the
        # counter and escape the worker's typed-failure contract.
        if proposal.prompt_tokens is not None and proposal.prompt_tokens > 0:
            self._llm_tokens_total.inc(proposal.prompt_tokens, labels=("prompt",))
        if proposal.completion_tokens is not None and proposal.completion_tokens > 0:
            self._llm_tokens_total.inc(proposal.completion_tokens, labels=("completion",))

        try:
            document = parse_metric_hypothesis(proposal.raw_json, allowed_signals=allowed)
        except LLMValidationError as exc:
            raise _TerminalFailure(exc.code) from None

        try:
            with self._stage_seconds.time(labels=("verify",)):
                verification = verify_hypothesis(document, ledger)
            evidence_payloads = tuple(
                (entry.evidence_id, metric_evidence_entry_json(entry)) for entry in ledger.entries
            )
            report_payload = verification_json(verification)
        except DomainError as exc:
            raise _TerminalFailure(exc.code) from None

        self._verdicts_total.inc(labels=(verification.verdict.value,))

        now = self._clock()
        with self._stage_seconds.time(labels=("persist",)):
            await uow.evidence.append(
                tuple(
                    EvidenceRecord(
                        tenant=investigation.tenant,
                        investigation_id=investigation.investigation_id,
                        run=investigation.run,
                        evidence_id=evidence_id,
                        ledger_kind=LedgerKind.METRIC,
                        schema_version=EVIDENCE_SCHEMA_VERSION,
                        payload=payload,
                        created_at=now,
                    )
                    for evidence_id, payload in evidence_payloads
                )
            )
            await uow.reports.put(
                ReportRecord(
                    investigation_id=investigation.investigation_id,
                    tenant=investigation.tenant,
                    run=investigation.run,
                    schema_version=VERIFICATION_SCHEMA_VERSION,
                    payload=report_payload,
                    created_at=now,
                )
            )
        await uow.investigations.set_status(
            investigation.tenant, investigation.investigation_id, InvestigationStatus.SUCCEEDED
        )
        await uow.audit.record(
            AuditRecord(
                tenant=investigation.tenant,
                investigation_id=investigation.investigation_id,
                actor=self._worker_id,
                action="report.persisted",
                detail=None,
                occurred_at=now,
            )
        )

    async def _retry_or_fail(
        self, uow: UnitOfWork, claimed: ClaimedJob, started: datetime, code: str
    ) -> None:
        if claimed.attempt_count >= self._max_attempts:
            await self._terminal_fail(uow, claimed, started, code)
            return
        await uow.jobs.set_status(claimed.tenant, claimed.job_id, JobStatus.QUEUED)
        await self._record_attempt(uow, claimed, started, AttemptOutcome.FAILED, code)
        self._jobs_total.inc(labels=("retried",))

    async def _terminal_fail(
        self, uow: UnitOfWork, claimed: ClaimedJob, started: datetime, code: str
    ) -> None:
        await uow.investigations.set_status(
            claimed.tenant, claimed.investigation_id, InvestigationStatus.FAILED
        )
        await uow.jobs.set_status(claimed.tenant, claimed.job_id, JobStatus.FAILED)
        await self._record_attempt(uow, claimed, started, AttemptOutcome.FAILED, code)
        self._jobs_total.inc(labels=("failed",))
        await uow.audit.record(
            AuditRecord(
                tenant=claimed.tenant,
                investigation_id=claimed.investigation_id,
                actor=self._worker_id,
                action="investigation.failed",
                detail=code,
                occurred_at=self._clock(),
            )
        )

    async def _record_attempt(
        self,
        uow: UnitOfWork,
        claimed: ClaimedJob,
        started: datetime,
        outcome: AttemptOutcome,
        error_code: str | None,
    ) -> None:
        await uow.attempts.record(
            AttemptRecord(
                attempt_id=AttemptId(self._id_factory()),
                job_id=claimed.job_id,
                tenant=claimed.tenant,
                attempt_number=claimed.attempt_count,
                worker_id=self._worker_id,
                started_at=started,
                finished_at=self._clock(),
                outcome=outcome,
                error_code=error_code,
                created_at=self._clock(),
            )
        )
