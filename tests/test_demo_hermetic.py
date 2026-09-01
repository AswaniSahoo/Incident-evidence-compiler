"""End-to-end test for the hermetic demo driver.

This runs ``scripts/demo_hermetic_investigation.py`` as a real subprocess, which in turn starts
``python -m incident_evidence_compiler`` on a loopback port and speaks HTTP to it. Nothing is
imported and called directly, so a break in the entrypoint, the config parsing, the ASGI wiring,
the worker loop or the report endpoint fails this test. It needs no network, no container and no
credential: the only telemetry is the committed RE2-OB fixture.

It is the slowest test in the suite (it pays for a uvicorn start plus one worker poll), so it is
bounded by an explicit 60 second timeout rather than left to hang.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "demo_hermetic_investigation.py"


class HermeticDemoTests(unittest.TestCase):
    def test_demo_script_runs_the_real_entrypoint_and_reports_a_verdict(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            # The driver bounds itself to about 75 s worst case (see its deadline constants), so
            # it always exits on its own before this timeout fires; if the timeout ever did fire
            # it would kill only the driver and orphan the server it started.
            timeout=90,
            cwd=ROOT,
            check=False,
        )
        output = completed.stdout
        detail = f"exit={completed.returncode}\nstdout:\n{output}\nstderr:\n{completed.stderr}"
        self.assertEqual(completed.returncode, 0, detail)
        self.assertIn("no model: labelled smoke client", output, detail)
        self.assertIn("no database: in-memory store", output, detail)
        self.assertIn("no network: loopback only", output, detail)
        self.assertIn("telemetry: committed synthetic fixture", output, detail)
        self.assertIn(
            "the API, worker, evidence ledger and verifier are the real ones", output, detail
        )
        self.assertIn("verdict: supported", output, detail)
        self.assertIn("p1: supported observed=increase supporting=1", output, detail)
        # Assert on lines the formatter's own fallback strings can never produce, so a broken
        # ranking payload ("baseline ranking: unavailable") fails here instead of passing.
        self.assertIn("baseline ranking (deterministic, no model): kind=ranking", output, detail)
        self.assertIn("  1. cpu", output, detail)
        self.assertNotIn("unavailable", output, detail)
        # The opaque case id is what reaches the prompt; the labelled directory must not appear.
        self.assertNotIn("CANARYSERVICE", output)
        self.assertNotIn("OTHERSERVICE", output)


if __name__ == "__main__":
    unittest.main()
