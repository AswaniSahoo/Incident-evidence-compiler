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

CHECKOUT_PIN = "34e114876b0b11c390a56381ad16ebd13914f8d5"
PYTHON_PIN = "a26af69be951a213d495a4c3e4e4022e16d87065"
UV_PIN = "11f9893b081a58869d3b5fccaea48c9e9e46f990"
PHASE0_RUNS = tuple(sorted(validator.PHASE0_CI_RUNS))
PHASE1_RUNS = tuple(sorted(validator.PHASE1_CI_RUNS))
PHASE2_RUNS = tuple(sorted(validator.EXPECTED_CI_RUNS_BY_PHASE[2]))


def workflow(
    *,
    runs: tuple[str, ...] = PHASE1_RUNS,
    checkout_ref: str = CHECKOUT_PIN,
    include_uv: bool = True,
) -> str:
    lines = [
        "name: test",
        "jobs:",
        "  governance:",
        "    steps:",
        "      - name: checkout",
        f"        uses: actions/checkout@{checkout_ref}",
        "      - name: python",
        f"        uses: actions/setup-python@{PYTHON_PIN}",
    ]
    if include_uv:
        lines.extend(("      - name: uv", f"        uses: astral-sh/setup-uv@{UV_PIN}"))
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
        (validator.ROOT / ".github" / "workflows" / "ci.yml").write_text(content, encoding="utf-8")

    def test_accepts_exact_executable_gates_and_pinned_actions(self) -> None:
        self.write_workflow(workflow())
        errors: list[str] = []
        validator._validate_ci(1, errors)
        self.assertEqual(errors, [])

    def test_accepts_accepted_phase0_ci_contract(self) -> None:
        self.write_workflow(workflow(runs=PHASE0_RUNS, include_uv=False))
        errors: list[str] = []
        validator._validate_ci(0, errors)
        self.assertEqual(errors, [])

    def test_accepts_phase2_ci_contract(self) -> None:
        self.write_workflow(workflow(runs=PHASE2_RUNS))
        errors: list[str] = []
        validator._validate_ci(2, errors)
        self.assertEqual(errors, [])

    def test_rejects_missing_commented_echoed_or_env_gate(self) -> None:
        missing = PHASE1_RUNS[0]
        remaining = PHASE1_RUNS[1:]
        variants = (
            workflow(runs=remaining),
            workflow(runs=remaining) + f"# run: {missing}\nrun: echo {missing}\n",
            workflow(runs=remaining)
            + "      - name: non-executable-value\n        env:\n"
            + f"          run: {missing}\n",
        )
        for text in variants:
            with self.subTest(text=text[-30:]):
                self.write_workflow(text)
                errors: list[str] = []
                validator._validate_ci(1, errors)
                self.assertTrue(any(missing in error for error in errors))

    def test_rejects_mutable_or_missing_required_action(self) -> None:
        self.write_workflow(workflow(checkout_ref="v4"))
        errors: list[str] = []
        validator._validate_ci(1, errors)
        self.assertTrue(any("full commit SHA" in error for error in errors))
        self.assertTrue(any("missing required immutable action" in error for error in errors))

    def test_rejects_pythonpath_bypass(self) -> None:
        self.write_workflow(workflow() + "env:\n  PYTHONPATH: src\n")
        errors: list[str] = []
        validator._validate_ci(1, errors)
        self.assertTrue(any("PYTHONPATH" in error for error in errors))

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
        (target / "incident-orchestrator.json").write_text(json.dumps(malformed), encoding="utf-8")
        errors: list[str] = []
        validator._validate_agent(errors)
        self.assertTrue(any("command must equal" in error for error in errors))


class PhasePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_root = validator.ROOT
        self.temporary = tempfile.TemporaryDirectory()
        validator.ROOT = Path(self.temporary.name)

    def tearDown(self) -> None:
        validator.ROOT = self.original_root
        self.temporary.cleanup()

    def write_context(self, phase: int) -> None:
        (validator.ROOT / "PROJECT_CONTEXT.md").write_text(
            f"# Context\n\n## Current phase\n\nPhase {phase} — fixture.\n",
            encoding="utf-8",
        )

    def test_phase0_rejects_each_phase1_artifact(self) -> None:
        for relative in ("src", "pyproject.toml", "uv.lock"):
            with self.subTest(relative=relative):
                target = validator.ROOT / relative
                if "." in target.name:
                    target.write_text("fixture\n", encoding="utf-8")
                else:
                    target.mkdir()
                errors: list[str] = []
                validator._validate_phase_scope(0, errors)
                self.assertTrue(any(relative in error for error in errors))
                target.rmdir() if target.is_dir() else target.unlink()

    def test_phase1_allows_only_contract_artifacts(self) -> None:
        (validator.ROOT / "src").mkdir()
        (validator.ROOT / "pyproject.toml").write_text("fixture\n", encoding="utf-8")
        (validator.ROOT / "uv.lock").write_text("fixture\n", encoding="utf-8")
        errors: list[str] = []
        validator._validate_phase_scope(1, errors)
        self.assertEqual(errors, [])
        (validator.ROOT / "app").mkdir()
        validator._validate_phase_scope(1, errors)
        self.assertTrue(any("app" in error for error in errors))

    def test_unsupported_phase_fails_closed(self) -> None:
        self.write_context(3)
        errors: list[str] = []
        self.assertIsNone(validator._current_phase(errors))
        self.assertTrue(any("unsupported project phase" in error for error in errors))

    def test_phase1_requires_contract_files(self) -> None:
        for relative in validator.BASE_REQUIRED_FILES + validator.PHASE_REQUIRED_FILES[1]:
            target = validator.ROOT / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fixture\n", encoding="utf-8")
        omitted = validator.PHASE_REQUIRED_FILES[1][0]
        (validator.ROOT / omitted).unlink()
        errors: list[str] = []
        validator._validate_required_files(1, errors)
        self.assertEqual(errors, [f"missing required file: {omitted}"])

    def test_phase2_required_files_are_cumulative(self) -> None:
        cumulative = (
            validator.BASE_REQUIRED_FILES
            + validator.PHASE_REQUIRED_FILES[1]
            + validator.PHASE_REQUIRED_FILES[2]
        )
        for relative in cumulative:
            target = validator.ROOT / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fixture\n", encoding="utf-8")
        omitted = validator.PHASE_REQUIRED_FILES[1][0]
        (validator.ROOT / omitted).unlink()
        errors: list[str] = []
        validator._validate_required_files(2, errors)
        self.assertEqual(errors, [f"missing required file: {omitted}"])

    def test_phase2_keeps_phase1_scope_and_tooling(self) -> None:
        (validator.ROOT / "src").mkdir()
        (validator.ROOT / "pyproject.toml").write_text("fixture\n", encoding="utf-8")
        (validator.ROOT / "uv.lock").write_text("fixture\n", encoding="utf-8")
        errors: list[str] = []
        validator._validate_phase_scope(2, errors)
        self.assertEqual(errors, [])
        (validator.ROOT / "eval").mkdir()
        validator._validate_phase_scope(2, errors)
        self.assertTrue(any("eval" in error for error in errors))

    def write_tooling(self, *, dependencies: str = "[]", lock_tools: bool = True) -> None:
        (validator.ROOT / "pyproject.toml").write_text(
            '[build-system]\nrequires = ["uv_build==0.11.17"]\n'
            'build-backend = "uv_build"\n[project]\n'
            'name = "incident-evidence-compiler"\nrequires-python = ">=3.12,<3.13"\n'
            f"dependencies = {dependencies}\n[dependency-groups]\n"
            'dev = ["mypy==2.1.0", "ruff==0.15.13"]\n'
            '[tool.uv]\nrequired-version = "==0.11.17"\n'
            '[tool.ruff]\ntarget-version = "py312"\n'
            '[tool.mypy]\npython_version = "3.12"\nstrict = true\n',
            encoding="utf-8",
        )
        packages = (
            '[[package]]\nname = "mypy"\nversion = "2.1.0"\n'
            '[[package]]\nname = "ruff"\nversion = "0.15.13"\n'
            if lock_tools
            else ""
        )
        (validator.ROOT / "uv.lock").write_text(
            'version = 1\n[[package]]\nname = "incident-evidence-compiler"\n'
            'version = "0.1.0"\nsource = { editable = "." }\n' + packages,
            encoding="utf-8",
        )

    def test_accepts_exact_phase1_tooling_contract(self) -> None:
        self.write_tooling()
        errors: list[str] = []
        validator._validate_phase1_tooling(errors)
        self.assertEqual(errors, [])

    def test_rejects_runtime_dependencies_and_stale_lock(self) -> None:
        self.write_tooling(dependencies='["requests"]', lock_tools=False)
        errors: list[str] = []
        validator._validate_phase1_tooling(errors)
        self.assertTrue(any("runtime dependencies" in error for error in errors))
        self.assertTrue(any("mypy==2.1.0" in error for error in errors))

    def test_rejects_raw_archives_and_extracted_trees(self) -> None:
        (validator.ROOT / "RE2-OB.zip").write_text("not data\n", encoding="utf-8")
        (validator.ROOT / "RE2-TT").mkdir()
        errors: list[str] = []
        validator._validate_dataset_policy(errors)
        self.assertTrue(any("raw RCAEval archive" in error for error in errors))
        self.assertTrue(any("extracted RCAEval tree" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
