from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE_REQUIRED_FILES = (
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    ".github/workflows/ci.yml",
    ".kiro/agents/incident-orchestrator.json",
    ".kiro/hooks/project_hook.py",
    ".kiro/settings/cli.json",
    ".kiro/steering/communication.md",
    ".kiro/steering/engineering.md",
    ".kiro/steering/product.md",
    ".kiro/steering/workflow.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "PROJECT_CONTEXT.md",
    "README.md",
    "docs/architecture/overview.md",
    "docs/decisions/0001-independent-rewrite.md",
    "docs/decisions/0002-product-scope.md",
    "docs/decisions/0003-development-workflow.md",
    "docs/devlog/0000-phase-0-foundation.md",
    "docs/devlog/README.md",
    "docs/provenance.md",
    "scripts/validate_project.py",
    "tests/test_project_hook.py",
    "tests/test_validate_project.py",
)
PHASE_REQUIRED_FILES: dict[int, tuple[str, ...]] = {
    0: (),
    1: (
        "docs/decisions/0004-phase-1-domain-baseline.md",
        "docs/devlog/0001-phase-1-domain-baseline.md",
        "docs/datasets/rcaeval-re2.md",
        "docs/datasets/rcaeval-re2.manifest.json",
        "pyproject.toml",
        "uv.lock",
        "src/incident_evidence_compiler/__init__.py",
        "src/incident_evidence_compiler/domain/__init__.py",
        "src/incident_evidence_compiler/domain/baseline.py",
        "src/incident_evidence_compiler/domain/errors.py",
        "src/incident_evidence_compiler/domain/identifiers.py",
        "src/incident_evidence_compiler/domain/incidents.py",
        "src/incident_evidence_compiler/domain/metrics.py",
        "src/incident_evidence_compiler/evaluation/rcaeval/adapter.py",
        "src/incident_evidence_compiler/evaluation/rcaeval/csv_loader.py",
        "src/incident_evidence_compiler/evaluation/rcaeval/discovery.py",
        "src/incident_evidence_compiler/evaluation/rcaeval/errors.py",
        "src/incident_evidence_compiler/evaluation/rcaeval/ids.py",
        "src/incident_evidence_compiler/evaluation/rcaeval/limits.py",
        "src/incident_evidence_compiler/evaluation/rcaeval/manifest.py",
        "src/incident_evidence_compiler/evaluation/rcaeval/sidecar.py",
        "tests/test_domain.py",
        "tests/test_package.py",
        "tests/test_rcaeval.py",
    ),
    2: (
        "docs/decisions/0005-phase-2-evidence-contracts.md",
        "docs/devlog/0002-phase-2-evidence-contracts.md",
        "src/incident_evidence_compiler/domain/evidence/__init__.py",
        "src/incident_evidence_compiler/domain/hypotheses.py",
        "src/incident_evidence_compiler/domain/serialization.py",
        "src/incident_evidence_compiler/domain/verifier.py",
        "tests/test_evidence.py",
        "tests/test_serialization.py",
        "tests/test_verifier.py",
    ),
    3: (
        "docs/decisions/0006-phase-3-change-events.md",
        "docs/devlog/0003-phase-3-change-events.md",
        "src/incident_evidence_compiler/domain/changes.py",
        "src/incident_evidence_compiler/domain/change_evidence.py",
        "src/incident_evidence_compiler/domain/change_hypotheses.py",
        "src/incident_evidence_compiler/domain/change_verifier.py",
        "tests/test_changes.py",
        "tests/test_change_verifier.py",
    ),
    4: (
        "docs/decisions/0011-persistence-boundary.md",
        "docs/devlog/0005-phase-4-persistence.md",
        "docker-compose.yml",
        "src/incident_evidence_compiler/persistence/__init__.py",
        "src/incident_evidence_compiler/persistence/errors.py",
        "src/incident_evidence_compiler/persistence/records.py",
        "src/incident_evidence_compiler/persistence/repositories.py",
        "src/incident_evidence_compiler/persistence/memory.py",
        "src/incident_evidence_compiler/persistence/migrations/0001_initial.sql",
        "src/incident_evidence_compiler/persistence/migrations/runner.py",
        "src/incident_evidence_compiler/persistence/postgres/unit_of_work.py",
        "tests/test_persistence.py",
        "tests/test_persistence_postgres.py",
    ),
    5: (
        "docs/decisions/0012-llm-provider-boundary.md",
        "docs/devlog/0006-phase-5-llm-provider.md",
        "src/incident_evidence_compiler/llm/__init__.py",
        "src/incident_evidence_compiler/llm/errors.py",
        "src/incident_evidence_compiler/llm/client.py",
        "src/incident_evidence_compiler/llm/parsing.py",
        "src/incident_evidence_compiler/llm/fake.py",
        "src/incident_evidence_compiler/llm/gemini.py",
        "tests/test_llm.py",
        "tests/test_llm_gemini.py",
    ),
    6: (
        "docs/decisions/0013-control-plane-worker.md",
        "docs/devlog/0007-phase-6-control-plane.md",
        "src/incident_evidence_compiler/application/__init__.py",
        "src/incident_evidence_compiler/application/errors.py",
        "src/incident_evidence_compiler/application/contracts.py",
        "src/incident_evidence_compiler/application/telemetry.py",
        "src/incident_evidence_compiler/application/use_cases.py",
        "src/incident_evidence_compiler/application/worker.py",
        "src/incident_evidence_compiler/api/__init__.py",
        "src/incident_evidence_compiler/api/app.py",
        "src/incident_evidence_compiler/api/auth.py",
        "tests/test_application.py",
        "tests/test_api.py",
    ),
    7: (
        "docs/decisions/0014-phase-7-real-data-evaluation.md",
        "docs/devlog/0008-phase-7-real-data-evaluation.md",
        "src/incident_evidence_compiler/evaluation/harness/__init__.py",
        "src/incident_evidence_compiler/evaluation/harness/baseline_inputs.py",
        "src/incident_evidence_compiler/evaluation/harness/scoring.py",
        "src/incident_evidence_compiler/evaluation/harness/runner.py",
        "scripts/run_evaluation.py",
        "tests/test_evaluation.py",
        "tests/test_real_data_integration.py",
        "docs/evaluation/re2-ob-baseline.json",
    ),
    8: (
        "docs/decisions/0015-phase-8-observability.md",
        "docs/devlog/0009-phase-8-observability.md",
        "src/incident_evidence_compiler/observability/__init__.py",
        "src/incident_evidence_compiler/observability/metrics.py",
        "tests/test_observability.py",
    ),
    9: (
        "docs/decisions/0016-runnable-entrypoint-container.md",
        "docs/devlog/0010-phase-9-runnable-entrypoint.md",
        "Dockerfile",
        "src/incident_evidence_compiler/__main__.py",
        "src/incident_evidence_compiler/runtime/__init__.py",
        "src/incident_evidence_compiler/runtime/config.py",
        "src/incident_evidence_compiler/runtime/telemetry.py",
        "src/incident_evidence_compiler/runtime/demo_llm.py",
        "src/incident_evidence_compiler/runtime/server.py",
        "tests/test_runtime.py",
    ),
}
REQUIRED_CONTEXT_HEADINGS = (
    "## Current phase",
    "## Current objective",
    "## Accepted decisions",
    "## Validation",
    "## Next action",
)
EXPECTED_SETTINGS: dict[str, Any] = {
    "chat.defaultAgent": "incident-orchestrator",
    "chat.enableCodeIntelligence": True,
    "chat.enableSubagent": True,
    "chat.enableTodoList": True,
}
EXPECTED_HOOKS: dict[str, tuple[tuple[str | None, str], ...]] = {
    "agentSpawn": ((None, "context"),),
    "userPromptSubmit": ((None, "log"),),
    "preToolUse": (("shell", "guard"), ("write", "guard")),
    "postToolUse": (("shell", "log"), ("write", "log")),
    "stop": ((None, "stop"),),
}
PHASE0_CI_RUNS = frozenset(
    {
        (
            "python -m py_compile scripts/validate_project.py "
            ".kiro/hooks/project_hook.py tests/test_project_hook.py "
            "tests/test_validate_project.py"
        ),
        'python -m unittest discover -s tests -p "test_*.py" -v',
        "python scripts/validate_project.py",
        "git show --check --oneline --format=fuller HEAD",
    }
)
PHASE1_CI_RUNS = frozenset(
    {
        "uv sync --locked",
        "uv run --locked python -m compileall -q src scripts .kiro/hooks tests",
        'uv run --locked python -m unittest discover -s tests -p "test_*.py" -v',
        "uv run --locked ruff check .",
        "uv run --locked ruff format --check .",
        "uv run --locked mypy src tests",
        "uv run --locked python scripts/validate_project.py",
        "git show --check --oneline --format=fuller HEAD",
    }
)
EXPECTED_CI_RUNS_BY_PHASE = {
    0: PHASE0_CI_RUNS,
    1: PHASE1_CI_RUNS,
    2: PHASE1_CI_RUNS,
    3: PHASE1_CI_RUNS,
    4: PHASE1_CI_RUNS,
    5: PHASE1_CI_RUNS,
    6: PHASE1_CI_RUNS,
    7: PHASE1_CI_RUNS,
    8: PHASE1_CI_RUNS,
    9: PHASE1_CI_RUNS,
}
BASE_REQUIRED_ACTIONS = frozenset(
    {
        "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
        "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
    }
)
PHASE1_REQUIRED_ACTIONS = BASE_REQUIRED_ACTIONS | {
    "astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990"
}
REQUIRED_ACTIONS_BY_PHASE = {
    0: BASE_REQUIRED_ACTIONS,
    1: PHASE1_REQUIRED_ACTIONS,
    2: PHASE1_REQUIRED_ACTIONS,
    3: PHASE1_REQUIRED_ACTIONS,
    4: PHASE1_REQUIRED_ACTIONS,
    5: PHASE1_REQUIRED_ACTIONS,
    6: PHASE1_REQUIRED_ACTIONS,
    7: PHASE1_REQUIRED_ACTIONS,
    8: PHASE1_REQUIRED_ACTIONS,
    9: PHASE1_REQUIRED_ACTIONS,
}
PINNED_ACTION = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")
FORBIDDEN_PHASE0_PATHS = (
    "app",
    "src",
    "data",
    "eval",
    "infra",
    "migrations",
    "pyproject.toml",
    "uv.lock",
    "Dockerfile",
    "docker-compose.yml",
    "LICENSE",
    "COPYING",
    "NOTICE",
)
PHASE1_SCOPE_EXCEPTIONS = {"src", "pyproject.toml", "uv.lock"}
PHASE4_SCOPE_EXCEPTIONS = {"docker-compose.yml"}
# Phase 9 ships the runnable container image (ADR 0016).
PHASE9_SCOPE_EXCEPTIONS = {"Dockerfile"}
# Approved runtime dependencies and their resolved lock pins, introduced per phase.
APPROVED_RUNTIME_DEPENDENCIES: dict[int, tuple[str, ...]] = {
    4: ("psycopg[binary]==3.3.4",),
    5: ("google-genai==2.12.1",),
    6: ("fastapi==0.139.2", "uvicorn[standard]==0.51.0"),
}
APPROVED_LOCK_PACKAGES: dict[int, tuple[tuple[str, str], ...]] = {
    4: (("psycopg", "3.3.4"),),
    5: (("google-genai", "2.12.1"),),
    6: (("fastapi", "0.139.2"), ("uvicorn", "0.51.0")),
}
LICENSE_ARTIFACTS = {"LICENSE", "COPYING", "NOTICE"}
TEXT_SUFFIXES = {".md", ".json", ".py", ".yml", ".yaml", ".toml", ".lock"}


def _current_phase(errors: list[str]) -> int | None:
    path = ROOT / "PROJECT_CONTEXT.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        errors.append("cannot read PROJECT_CONTEXT.md current phase")
        return None
    match = re.search(r"^## Current phase\s*\n\s*Phase (\d+)\b", text, re.MULTILINE)
    if match is None:
        errors.append("PROJECT_CONTEXT.md current phase is malformed")
        return None
    phase = int(match.group(1))
    if phase not in PHASE_REQUIRED_FILES:
        errors.append(f"unsupported project phase: {phase}; update governance first")
        return None
    return phase


def _validate_required_files(phase: int, errors: list[str]) -> None:
    required = BASE_REQUIRED_FILES + tuple(
        relative
        for phase_number in range(phase + 1)
        for relative in PHASE_REQUIRED_FILES[phase_number]
    )
    for relative in required:
        if not (ROOT / relative).is_file():
            errors.append(f"missing required file: {relative}")


def _read_json(relative: str, errors: list[str]) -> dict[str, Any]:
    path = ROOT / relative
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid JSON in {relative}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"expected a JSON object in {relative}")
        return {}
    return value


def _read_toml(relative: str, errors: list[str]) -> dict[str, Any]:
    path = ROOT / relative
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"invalid TOML in {relative}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"expected a TOML table in {relative}")
        return {}
    return value


def _validate_context(errors: list[str]) -> None:
    path = ROOT / "PROJECT_CONTEXT.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    for heading in REQUIRED_CONTEXT_HEADINGS:
        if heading not in text:
            errors.append(f"PROJECT_CONTEXT.md missing heading: {heading}")
    if "Last verified:" not in text:
        errors.append("PROJECT_CONTEXT.md must include a Last verified date")


def _validate_agent(errors: list[str]) -> None:
    relative = ".kiro/agents/incident-orchestrator.json"
    value = _read_json(relative, errors)
    if value.get("name") != "incident-orchestrator":
        errors.append(f"{relative} must use the incident-orchestrator name")

    tools = value.get("tools")
    allowed_tools = value.get("allowedTools")
    if not isinstance(tools, list) or not all(isinstance(item, str) for item in tools):
        errors.append(f"{relative} tools must be a string list")
        tools = []
    if not isinstance(allowed_tools, list) or not all(
        isinstance(item, str) for item in allowed_tools
    ):
        errors.append(f"{relative} allowedTools must be a string list")
        allowed_tools = []
    if not set(allowed_tools).issubset(tools):
        errors.append(f"{relative} allowedTools must be a subset of tools")
    if {"shell", "write"}.intersection(allowed_tools):
        errors.append(f"{relative} must not auto-allow shell or write")

    resources = value.get("resources")
    if not isinstance(resources, list) or "file://PROJECT_CONTEXT.md" not in resources:
        errors.append(f"{relative} must load PROJECT_CONTEXT.md")

    hooks = value.get("hooks")
    if not isinstance(hooks, dict):
        errors.append(f"{relative} hooks must be an object")
        return
    if set(hooks) != set(EXPECTED_HOOKS):
        errors.append(f"{relative} hook triggers must exactly match project policy")
    for trigger, expected_entries in EXPECTED_HOOKS.items():
        entries = hooks.get(trigger)
        if not isinstance(entries, list) or len(entries) != len(expected_entries):
            errors.append(f"{relative} {trigger} hook count is invalid")
            continue
        for index, ((expected_matcher, action), entry) in enumerate(
            zip(expected_entries, entries, strict=True)
        ):
            if not isinstance(entry, dict):
                errors.append(f"{relative} {trigger}[{index}] must be an object")
                continue
            expected_command = f"python .kiro/hooks/project_hook.py {action}"
            if entry.get("command") != expected_command:
                errors.append(
                    f"{relative} {trigger}[{index}] command must equal {expected_command!r}"
                )
            matcher = entry.get("matcher")
            if matcher != expected_matcher:
                errors.append(
                    f"{relative} {trigger}[{index}] matcher must equal {expected_matcher!r}"
                )


def _validate_settings(errors: list[str]) -> None:
    relative = ".kiro/settings/cli.json"
    value = _read_json(relative, errors)
    for key, expected in EXPECTED_SETTINGS.items():
        if value.get(key) != expected:
            errors.append(f"{relative} must set {key} to {expected!r}")


def _license_recorded() -> bool:
    """True once a license decision ADR exists, which unblocks license artifacts."""
    return any((ROOT / "docs" / "decisions").glob("*license*.md"))


def _validate_phase_scope(phase: int, errors: list[str]) -> None:
    forbidden = set(FORBIDDEN_PHASE0_PATHS)
    if phase >= 1:
        forbidden -= PHASE1_SCOPE_EXCEPTIONS
    if phase >= 4:
        forbidden -= PHASE4_SCOPE_EXCEPTIONS
    if phase >= 9:
        forbidden -= PHASE9_SCOPE_EXCEPTIONS
    if _license_recorded():
        forbidden -= LICENSE_ARTIFACTS
    for relative in sorted(forbidden):
        if (ROOT / relative).exists():
            errors.append(
                f"Phase {phase} must not contain runtime or undecided artifact: {relative}"
            )


def _validate_provenance(errors: list[str]) -> None:
    provenance = ROOT / "docs" / "provenance.md"
    if provenance.is_file():
        text = provenance.read_text(encoding="utf-8")
        if "https://github.com/yashprogrammer/EnterpriseRAG_live" not in text:
            errors.append("provenance must identify the audited upstream repository")
        if "96cbbd3a7e4f012240c48c1fead9c838e9bb1b6b" not in text:
            errors.append("provenance must pin the audited upstream commit")
        if "No source files are copied" not in text:
            errors.append("provenance must state the clean-room source boundary")


def _validate_dataset_policy(errors: list[str]) -> None:
    archive_names = {"RE2-OB.zip", "RE2-SS.zip", "RE2-TT.zip"}
    synthetic_root = ROOT / "tests" / "fixtures" / "rcaeval"
    for path in ROOT.rglob("*"):
        if ".git" in path.parts:
            continue
        if path.name in archive_names:
            errors.append(f"raw RCAEval archive is forbidden: {path.relative_to(ROOT)}")
        if path.is_dir() and path.name in {"RE2-OB", "RE2-SS", "RE2-TT"}:
            try:
                path.relative_to(synthetic_root)
            except ValueError:
                errors.append(f"extracted RCAEval tree is forbidden: {path.relative_to(ROOT)}")
        if path.is_file() and "sidecar" in path.name.lower():
            try:
                path.relative_to(ROOT / "artifacts" / "evaluation-sidecars")
            except ValueError:
                if "src" not in path.parts and "tests" not in path.parts:
                    relative = path.relative_to(ROOT)
                    errors.append(
                        f"evaluation sidecar must remain under ignored artifacts: {relative}"
                    )


def _expected_runtime_dependencies(phase: int) -> list[str]:
    result: list[str] = []
    for number in range(1, phase + 1):
        result.extend(APPROVED_RUNTIME_DEPENDENCIES.get(number, ()))
    return result


def _expected_lock_packages(phase: int) -> list[tuple[str, str]]:
    packages: list[tuple[str, str]] = [("mypy", "2.1.0"), ("ruff", "0.15.13")]
    for number in range(1, phase + 1):
        packages.extend(APPROVED_LOCK_PACKAGES.get(number, ()))
    return packages


def _validate_phase1_tooling(phase: int, errors: list[str]) -> None:
    project_file = _read_toml("pyproject.toml", errors)
    project = project_file.get("project", {})
    build = project_file.get("build-system", {})
    groups = project_file.get("dependency-groups", {})
    tools = project_file.get("tool", {})
    if not isinstance(project, dict) or project.get("name") != "incident-evidence-compiler":
        errors.append("pyproject project name must be incident-evidence-compiler")
        project = {}
    if project.get("requires-python") != ">=3.12,<3.13":
        errors.append("pyproject requires-python must equal >=3.12,<3.13")
    dependencies = project.get("dependencies")
    if (
        not isinstance(dependencies, list)
        or not all(isinstance(item, str) for item in dependencies)
        or sorted(dependencies) != sorted(_expected_runtime_dependencies(phase))
    ):
        errors.append("runtime dependencies must match the approved set for the current phase")
    if "optional-dependencies" in project:
        errors.append("project must not declare optional runtime dependencies")
    if not isinstance(build, dict) or build.get("requires") != ["uv_build==0.11.17"]:
        errors.append("build backend requirement must equal uv_build==0.11.17")
    if not isinstance(build, dict) or build.get("build-backend") != "uv_build":
        errors.append("build backend must equal uv_build")
    dev = groups.get("dev") if isinstance(groups, dict) else None
    if not isinstance(dev, list) or set(dev) != {"mypy==2.1.0", "ruff==0.15.13"}:
        errors.append("development tools must exactly pin mypy==2.1.0 and ruff==0.15.13")
    if not isinstance(tools, dict):
        tools = {}
    uv = tools.get("uv", {})
    ruff = tools.get("ruff", {})
    mypy = tools.get("mypy", {})
    if not isinstance(uv, dict) or uv.get("required-version") != "==0.11.17":
        errors.append("tool.uv.required-version must equal ==0.11.17")
    if not isinstance(ruff, dict) or ruff.get("target-version") != "py312":
        errors.append("tool.ruff.target-version must equal py312")
    if (
        not isinstance(mypy, dict)
        or mypy.get("python_version") != "3.12"
        or mypy.get("strict") is not True
    ):
        errors.append("mypy must target Python 3.12 in strict mode")

    lock = _read_toml("uv.lock", errors)
    packages = lock.get("package", [])
    if not isinstance(packages, list):
        errors.append("uv.lock packages must be an array")
        return
    for name, version in _expected_lock_packages(phase):
        matches = [
            package
            for package in packages
            if isinstance(package, dict)
            and package.get("name") == name
            and package.get("version") == version
        ]
        if len(matches) != 1:
            errors.append(f"uv.lock must contain exactly one {name}=={version}")
    roots = [
        package
        for package in packages
        if isinstance(package, dict) and package.get("name") == "incident-evidence-compiler"
    ]
    if len(roots) != 1 or roots[0].get("source") != {"editable": "."}:
        errors.append("uv.lock must contain the editable incident-evidence-compiler root")


def _workflow_steps(text: str) -> tuple[dict[str, str], ...]:
    lines = text.splitlines()
    starts = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^ {6}- [A-Za-z][A-Za-z-]*:\s*", line)
    ]
    steps: list[dict[str, str]] = []
    scalar_pattern = re.compile(r"^ {8}([A-Za-z][A-Za-z-]*):\s*(.*)$")
    first_pattern = re.compile(r"^ {6}- ([A-Za-z][A-Za-z-]*):\s*(.*)$")
    for position, start in enumerate(starts):
        stop = starts[position + 1] if position + 1 < len(starts) else len(lines)
        first = first_pattern.match(lines[start])
        if first is None:
            continue
        step = {first.group(1): first.group(2).split(" #", 1)[0].strip()}
        for line in lines[start + 1 : stop]:
            match = scalar_pattern.match(line)
            if match is not None:
                step[match.group(1)] = match.group(2).split(" #", 1)[0].strip()
        steps.append(step)
    return tuple(steps)


def _is_unconditional_fatal_step(step: dict[str, str]) -> bool:
    return "if" not in step and step.get("continue-on-error", "false").lower() == "false"


def _validate_ci(phase: int, errors: list[str]) -> None:
    path = ROOT / ".github" / "workflows" / "ci.yml"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    steps = _workflow_steps(text)
    for command in EXPECTED_CI_RUNS_BY_PHASE[phase]:
        matching = [step for step in steps if step.get("run") == command]
        if not matching:
            errors.append(f"CI workflow missing executable step: {command}")
        elif not any(_is_unconditional_fatal_step(step) for step in matching):
            errors.append(f"CI gate must be unconditional and fatal: {command}")
    uses = [step["uses"] for step in steps if "uses" in step]
    if not uses:
        errors.append("CI workflow must declare immutable action dependencies")
    for action in uses:
        if not PINNED_ACTION.fullmatch(action):
            errors.append(f"CI action must be pinned to a full commit SHA: {action}")
    for action in REQUIRED_ACTIONS_BY_PHASE[phase]:
        matching = [step for step in steps if step.get("uses") == action]
        if not matching:
            errors.append(f"CI workflow missing required immutable action: {action}")
        elif not any(_is_unconditional_fatal_step(step) for step in matching):
            errors.append(f"CI action must be unconditional and fatal: {action}")
    if "PYTHONPATH" in text:
        errors.append("CI workflow must not set PYTHONPATH")


def _validate_text_hygiene(errors: list[str]) -> None:
    for path in ROOT.rglob("*"):
        if (
            not path.is_file()
            or ".git" in path.parts
            or ".venv" in path.parts
            or "__pycache__" in path.parts
            or (".kiro" in path.parts and "logs" in path.parts)
        ):
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name not in {".editorconfig", ".gitignore"}:
            continue
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT)
        if text and not text.endswith("\n"):
            errors.append(f"missing final newline: {relative}")
        if text.endswith("\n\n"):
            errors.append(f"extra blank line at end of file: {relative}")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line != line.rstrip():
                errors.append(f"trailing whitespace: {relative}:{line_number}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate repository governance files")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="run the inexpensive context/JSON checks used by the stop hook",
    )
    args = parser.parse_args()

    errors: list[str] = []
    phase = _current_phase(errors)
    if phase is None:
        print("project validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    _validate_required_files(phase, errors)
    _validate_context(errors)
    _validate_agent(errors)
    _validate_settings(errors)
    _validate_text_hygiene(errors)
    if not args.quick:
        _validate_phase_scope(phase, errors)
        _validate_provenance(errors)
        _validate_dataset_policy(errors)
        if phase >= 1:
            _validate_phase1_tooling(phase, errors)
        _validate_ci(phase, errors)

    if errors:
        print("project validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    mode = "quick" if args.quick else "full"
    print(f"project validation passed ({mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
