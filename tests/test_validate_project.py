from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "scripts" / "validate_project.py"
SPEC = importlib.util.spec_from_file_location("validate_project", VALIDATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)

PIN = "a" * 40
VALID_RUNS = tuple(sorted(validator.EXPECTED_CI_RUNS))


def workflow(*, runs: tuple[str, ...] = VALID_RUNS, action_ref: str = PIN) -> str:
    lines = [
        "name: test",
        "jobs:",
        "  governance:",
        "    steps:",
        "      - name: dependency",
        f"        uses: actions/checkout@{action_ref}",
    ]
    for command in runs:
        lines.extend(("      - name: gate", f"        run: {command}"))
    return "\n".join(lines) + "\n"


class ValidatorFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_root = validator.ROOT
        self.temporary = tempfile.TemporaryDirectory()
        validator.ROOT = Path(self.temporary.name)
        (validator.ROOT / ".github" / "workflows").mkdir(parents=True)

    def tearDown(self) -> None:
        validator.ROOT = self.original_root
        self.temporary.cleanup()

    def write_workflow(self, content: str) -> None:
        (validator.ROOT / ".github" / "workflows" / "ci.yml").write_text(
            content, encoding="utf-8"
        )

    def test_accepts_exact_executable_gates_and_pinned_action(self) -> None:
        self.write_workflow(workflow())
        errors: list[str] = []
        validator._validate_ci(errors)
        self.assertEqual(errors, [])

    def test_rejects_missing_gate(self) -> None:
        self.write_workflow(workflow(runs=VALID_RUNS[:-1]))
        errors: list[str] = []
        validator._validate_ci(errors)
        self.assertTrue(any("missing executable step" in error for error in errors))

    def test_rejects_commented_or_echoed_gate(self) -> None:
        missing = VALID_RUNS[0]
        remaining = VALID_RUNS[1:]
        text = workflow(runs=remaining)
        text += f"# run: {missing}\nrun: echo {missing}\n"
        self.write_workflow(text)
        errors: list[str] = []
        validator._validate_ci(errors)
        self.assertTrue(any(missing in error for error in errors))

    def test_rejects_mutable_action_reference(self) -> None:
        self.write_workflow(workflow(action_ref="v4"))
        errors: list[str] = []
        validator._validate_ci(errors)
        self.assertTrue(any("full commit SHA" in error for error in errors))

    def test_rejects_command_outside_step_execution_context(self) -> None:
        missing = VALID_RUNS[0]
        text = workflow(runs=VALID_RUNS[1:])
        text += (
            "      - name: non-executable-value\n"
            "        env:\n"
            f"          run: {missing}\n"
        )
        self.write_workflow(text)
        errors: list[str] = []
        validator._validate_ci(errors)
        self.assertTrue(any(missing in error for error in errors))

    def test_rejects_malformed_hook_command(self) -> None:
        source = json.loads(
            (self.original_root / ".kiro" / "agents" / "incident-orchestrator.json").read_text(
                encoding="utf-8"
            )
        )
        malformed = copy.deepcopy(source)
        malformed["hooks"]["stop"][0]["command"] = "echo validation skipped"
        target = validator.ROOT / ".kiro" / "agents"
        target.mkdir(parents=True)
        (target / "incident-orchestrator.json").write_text(
            json.dumps(malformed), encoding="utf-8"
        )
        errors: list[str] = []
        validator._validate_agent(errors)
        self.assertTrue(any("command must equal" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
