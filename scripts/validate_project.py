from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
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
EXPECTED_CI_RUNS = frozenset(
    {
        "python -m py_compile scripts/validate_project.py .kiro/hooks/project_hook.py tests/test_project_hook.py tests/test_validate_project.py",
        'python -m unittest discover -s tests -p "test_*.py" -v',
        "python scripts/validate_project.py",
        "git show --check --oneline --format=fuller HEAD",
    }
)
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
TEXT_SUFFIXES = {".md", ".json", ".py", ".yml", ".yaml"}


def _validate_required_files(errors: list[str]) -> None:
    for relative in REQUIRED_FILES:
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
                errors.append(f"{relative} {trigger}[{index}] command must equal {expected_command!r}")
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


def _validate_phase0_scope(errors: list[str]) -> None:
    for relative in FORBIDDEN_PHASE0_PATHS:
        if (ROOT / relative).exists():
            errors.append(f"Phase 0 must not contain runtime or undecided artifact: {relative}")
    provenance = ROOT / "docs" / "provenance.md"
    if provenance.is_file():
        text = provenance.read_text(encoding="utf-8")
        if "https://github.com/yashprogrammer/EnterpriseRAG_live" not in text:
            errors.append("provenance must identify the audited upstream repository")
        if "96cbbd3a7e4f012240c48c1fead9c838e9bb1b6b" not in text:
            errors.append("provenance must pin the audited upstream commit")
        if "No source files are copied" not in text:
            errors.append("provenance must state the clean-room source boundary")


def _workflow_step_values(text: str, key: str) -> list[str]:
    lines = text.splitlines()
    values: list[str] = []
    step_pattern = re.compile(r"^ {6}- name:\s+\S")
    value_pattern = re.compile(rf"^ {{8}}{re.escape(key)}:\s+(.+)$")
    for index, line in enumerate(lines[:-1]):
        if not step_pattern.match(line):
            continue
        next_index = index + 1
        while next_index < len(lines) and not lines[next_index].strip():
            next_index += 1
        if next_index >= len(lines):
            continue
        match = value_pattern.match(lines[next_index])
        if match:
            values.append(match.group(1).split(" #", 1)[0].strip())
    return values


def _validate_ci(errors: list[str]) -> None:
    path = ROOT / ".github" / "workflows" / "ci.yml"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    runs = frozenset(_workflow_step_values(text, "run"))
    for command in EXPECTED_CI_RUNS:
        if command not in runs:
            errors.append(f"CI workflow missing executable step: {command}")
    uses = _workflow_step_values(text, "uses")
    if not uses:
        errors.append("CI workflow must declare immutable action dependencies")
    for action in uses:
        if not PINNED_ACTION.fullmatch(action):
            errors.append(f"CI action must be pinned to a full commit SHA: {action}")


def _validate_text_hygiene(errors: list[str]) -> None:
    for path in ROOT.rglob("*"):
        if (
            not path.is_file()
            or ".git" in path.parts
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
    _validate_required_files(errors)
    _validate_context(errors)
    _validate_agent(errors)
    _validate_settings(errors)
    _validate_text_hygiene(errors)
    if not args.quick:
        _validate_phase0_scope(errors)
        _validate_ci(errors)

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
