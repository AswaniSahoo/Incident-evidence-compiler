"""Phase 7a: real-shaped data through the adapter, bridge, and worker.

The hermetic tests flow the committed leakage fixture (which carries the
``CANARYSERVICE``/``OTHERSERVICE``/``DO_NOT_LEAK_PATH`` sentinels) through the
RCAEval adapter, the baseline-input bridge, and the full worker pipeline over the
in-memory persistence fake and ``FakeLLMClient`` — then assert that no ground-truth
label or source locator appears on any persisted evidence or report surface.

An additional opt-in test runs the harness against a real, out-of-repo RE2-OB split
when ``IEC_RE2_OB_ROOT`` points to it; it is skipped in the hermetic gate so CI needs
no dataset, network, or credentials (ADR 0009).
"""

import asyncio
import json
import os
import unittest
from pathlib import Path

from incident_evidence_compiler.application import (
    CreateInvestigation,
    CreateInvestigationCommand,
    GetReport,
    InMemoryTelemetrySource,
    Worker,
)
from incident_evidence_compiler.domain.identifiers import IncidentId, RunId, TenantId
from incident_evidence_compiler.evaluation.harness import Arm, evaluate_batch, summary_json
from incident_evidence_compiler.evaluation.harness.baseline_inputs import to_baseline_inputs
from incident_evidence_compiler.evaluation.rcaeval import RcaevalAdapter
from incident_evidence_compiler.llm import FakeLLMClient
from incident_evidence_compiler.persistence import (
    InMemoryUnitOfWorkFactory,
    InvestigationStatus,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "rcaeval" / "RE2-OB"
CANARIES = ("CANARYSERVICE", "CANARYFAULT", "OTHERSERVICE", "OTHERFAULT", "DO_NOT_LEAK_PATH")

_TENANT = "tenant-eval"
_INCIDENT = "inc-eval"
_RUN = "run-eval"


def _proposal(signal_key: str) -> str:
    return json.dumps(
        {
            "hypothesis_id": "h1",
            "tenant_id": _TENANT,
            "incident_id": _INCIDENT,
            "run_id": _RUN,
            "semantics": "descriptive",
            "composition": "all",
            "predicates": [
                {"predicate_id": "p1", "signal_key": signal_key, "expected_direction": "increase"}
            ],
        }
    )


class RealShapedWorkerPipelineTest(unittest.IsolatedAsyncioTestCase):
    async def test_fixture_flows_through_worker_without_leaking_labels(self) -> None:
        batch = RcaevalAdapter().load(FIXTURE_ROOT, "OB")
        case = next(case for case in batch.cases if any(s.key.value == "cpu" for s in case.signals))
        inputs = to_baseline_inputs(case.signals)

        factory = InMemoryUnitOfWorkFactory()
        telemetry = InMemoryTelemetrySource()
        telemetry.set(TenantId(_TENANT), IncidentId(_INCIDENT), RunId(_RUN), inputs)
        worker = Worker(factory, FakeLLMClient([_proposal("cpu")]), telemetry, worker_id="worker-1")

        command = CreateInvestigationCommand(
            tenant=TenantId(_TENANT),
            incident=IncidentId(_INCIDENT),
            run=RunId(_RUN),
            window=case.window,
        )
        investigation_id = await CreateInvestigation(factory).execute(command)
        self.assertTrue(await worker.run_once())

        report = await GetReport(factory).execute(TenantId(_TENANT), investigation_id)
        async with factory() as uow:
            investigation = await uow.investigations.get(TenantId(_TENANT), investigation_id)
            evidence = await uow.evidence.list_for_investigation(
                TenantId(_TENANT), investigation_id
            )
        self.assertEqual(investigation.status, InvestigationStatus.SUCCEEDED)
        self.assertGreaterEqual(len(evidence), 1)

        surfaces = [report.payload, repr(investigation), repr(case), str(FIXTURE_ROOT)]
        surfaces.extend(record.payload for record in evidence)
        combined = "\n".join(surfaces)
        for canary in CANARIES:
            with self.subTest(canary=canary):
                self.assertNotIn(canary, combined)


class OptInRealDataTest(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("IEC_RE2_OB_ROOT") and Path(os.environ["IEC_RE2_OB_ROOT"]).is_dir(),
        "set IEC_RE2_OB_ROOT to an extracted out-of-repo RE2-OB directory to run",
    )
    def test_real_re2_ob_baseline_runs_and_stays_label_safe(self) -> None:
        root = Path(os.environ["IEC_RE2_OB_ROOT"])
        batch = RcaevalAdapter().load(root, "OB", skip_unparsable_cases=True)
        self.assertGreater(len(batch.cases), 0)
        summary = asyncio.run(evaluate_batch(batch, arm=Arm.BASELINE))
        self.assertEqual(summary.case_count, len(batch.cases))
        # No cited evidence id can be invalid on the deterministic arm.
        self.assertEqual(summary.invalid_evidence_id_count, 0)
        # The aggregate surface must not embed the out-of-repo path.
        self.assertNotIn(str(root), summary_json(summary))


if __name__ == "__main__":
    unittest.main()
