from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / ".kiro" / "logs" / "session-events.jsonl"
MAX_LOG_BYTES = 1_000_000
LOG_KEYS = frozenset(
    {"timestamp", "session_id", "event", "tool", "branch", "commit", "dirty", "git_status"}
)
SESSION_FINGERPRINT = re.compile(r"^[0-9a-f]{16}$")
COMMIT_VALUE = re.compile(r"^(?:none|[0-9a-f]{7,40})$")
SAFE_LABEL = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
BRANCH_CATEGORIES = frozenset({"main", "phase", "feature", "other", "unknown"})
HOOK_EVENTS = frozenset({"agentSpawn", "userPromptSubmit", "preToolUse", "postToolUse", "stop"})
GIT_STATUS_VALUES = frozenset({"ok", "unavailable"})
SAFE_TOKEN = re.compile(r"[^A-Za-z0-9_.:-]+")


def _read_event() -> dict[str, Any] | None:
    raw = sys.stdin.read()
    if not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _git(*args: str) -> tuple[int, str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout.strip()


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _branch_category(branch: str) -> str:
    if branch == "main":
        return "main"
    if branch.startswith("phase/"):
        return "phase"
    if branch.startswith("feature/"):
        return "feature"
    if not branch:
        return "unknown"
    return "other"


def _git_state() -> dict[str, Any]:
    branch_code, branch = _git("branch", "--show-current")
    commit_code, commit = _git("rev-parse", "--short", "HEAD")
    status_code, porcelain = _git("status", "--porcelain")
    if branch_code:
        branch = ""
    return {
        "branch": _branch_category(branch),
        "commit": commit if not commit_code and commit else "none",
        "dirty": bool(porcelain) if not status_code else None,
        "git_status": "ok" if not (branch_code or status_code) else "unavailable",
    }


def _safe_label(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = SAFE_TOKEN.sub("_", str(value))[:64]
    return cleaned or "unknown"


def _timestamp_is_safe(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _record_is_safe(record: Any) -> bool:
    if not isinstance(record, dict) or set(record) != LOG_KEYS:
        return False
    tool = record.get("tool")
    return all(
        (
            _timestamp_is_safe(record.get("timestamp")),
            bool(SESSION_FINGERPRINT.fullmatch(str(record.get("session_id", "")))),
            record.get("event") in HOOK_EVENTS,
            tool is None or (isinstance(tool, str) and bool(SAFE_LABEL.fullmatch(tool))),
            record.get("branch") in BRANCH_CATEGORIES,
            bool(COMMIT_VALUE.fullmatch(str(record.get("commit", "")))),
            isinstance(record.get("dirty"), bool) or record.get("dirty") is None,
            record.get("git_status") in GIT_STATUS_VALUES,
        )
    )


def _log_file_is_safe(path: Path) -> bool:
    try:
        return all(
            _record_is_safe(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False


def _scrub_unsafe_logs() -> None:
    rotated = LOG_PATH.with_suffix(LOG_PATH.suffix + ".1")
    for path in (LOG_PATH, rotated):
        if path.exists() and not _log_file_is_safe(path):
            path.unlink()


def _rotate_log() -> None:
    if not LOG_PATH.exists() or LOG_PATH.stat().st_size < MAX_LOG_BYTES:
        return
    rotated = LOG_PATH.with_suffix(LOG_PATH.suffix + ".1")
    rotated.unlink(missing_ok=True)
    LOG_PATH.replace(rotated)


def _append_log(event: dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _scrub_unsafe_logs()
    _rotate_log()
    raw_session = os.environ.get("KIRO_SESSION_ID", "unknown")
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": _fingerprint(raw_session),
        "event": _safe_label(event.get("hook_event_name")),
        "tool": _safe_label(event.get("tool_name")),
        **_git_state(),
    }
    if not _record_is_safe(record):
        raise ValueError("refusing to persist unsafe hook metadata")
    descriptor = os.open(LOG_PATH, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    try:
        os.chmod(LOG_PATH, 0o600)
    except OSError:
        pass


def _context(event: dict[str, Any]) -> int:
    _append_log(event)
    context = (ROOT / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
    state = _git_state()
    print(context)
    print("\n## Live Git metadata")
    print(f"- Branch category: {state['branch']}")
    print(f"- Commit: {state['commit']}")
    print(f"- Dirty: {state['dirty']}")
    return 0


def _git_invocations(command: str) -> list[tuple[str, list[str]]] | None:
    invocations: list[tuple[str, list[str]]] = []
    for segment in re.split(r"[;&|\r\n]+", command):
        if not re.search(r"(?:^|\s)git(?:\.exe)?(?:\s|$)", segment, flags=re.IGNORECASE):
            continue
        try:
            tokens = shlex.split(segment, posix=False)
        except ValueError:
            return None
        git_index = next(
            (
                index
                for index, token in enumerate(tokens)
                if Path(token.strip('"\'')).name.casefold() in {"git", "git.exe"}
            ),
            None,
        )
        if git_index is None:
            continue
        index = git_index + 1
        while index < len(tokens):
            token = tokens[index].strip('"\'')
            lowered = token.casefold()
            if lowered in {"-c", "-c", "--git-dir", "--work-tree", "--namespace"}:
                index += 2
                continue
            if lowered.startswith(("--git-dir=", "--work-tree=", "--namespace=")):
                index += 1
                continue
            if token == "-C":
                index += 2
                continue
            if token.startswith("-"):
                index += 1
                continue
            args = [item.strip('"\'') for item in tokens[index + 1 :]]
            invocations.append((lowered, args))
            break
    return invocations


def _is_disallowed_git_command(command: str) -> bool:
    invocations = _git_invocations(command)
    if invocations is None:
        return True
    for subcommand, arguments in invocations:
        lowered = [argument.casefold() for argument in arguments]
        if subcommand == "push":
            return True
        if subcommand == "reset" and "--hard" in lowered:
            return True
        if subcommand == "clean" and any(
            argument == "--force"
            or (argument.startswith("-") and not argument.startswith("--") and "f" in argument[1:])
            for argument in lowered
        ):
            return True
        if subcommand == "commit" and any(
            argument in {"--amend", "--no-verify", "-n"}
            or (
                argument.startswith("-")
                and not argument.startswith("--")
                and "n" in argument[1:]
            )
            for argument in lowered
        ):
            return True
        if subcommand == "add" and any(
            argument in {".", ":/", "--all", "-a"} for argument in lowered
        ):
            return True
        if subcommand == "branch":
            short_force = any(
                argument.startswith("-")
                and not argument.startswith("--")
                and ("f" in argument[1:].casefold() or argument in {"-D", "-M", "-C"})
                for argument in arguments
            )
            long_force_or_delete = any(
                argument.casefold() in {"--delete", "--force"} for argument in arguments
            )
            if short_force or long_force_or_delete or "-d" in arguments:
                return True
        if subcommand in {"checkout", "restore"} and any(
            argument in {".", ":/"} for argument in lowered
        ):
            return True
    return False


def _blocked(message: str) -> int:
    print(f"Blocked by project policy: {message}", file=sys.stderr)
    return 2


def _guard(event: dict[str, Any] | None) -> int:
    if event is None:
        return _blocked("covered tool event was missing or malformed")
    tool_name = str(event.get("tool_name", ""))
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return _blocked("covered tool input was missing or malformed")

    if "shell" in tool_name or tool_name in {"execute_bash", "execute_cmd"}:
        command = tool_input.get("command")
        if not isinstance(command, str) or not command.strip():
            return _blocked("shell command was missing or malformed")
        if _is_disallowed_git_command(command):
            return _blocked("the command matched a disallowed Git form")

    if "write" in tool_name or tool_name in {"fs_write", "fsWrite"}:
        candidate = tool_input.get("path")
        if not isinstance(candidate, str) or not candidate.strip():
            return _blocked("write path was missing or malformed")
        path = Path(candidate)
        resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
        try:
            resolved.relative_to(ROOT)
        except ValueError:
            return _blocked("the write tool may only target the project workspace")
        if any(part.casefold() == ".git" for part in resolved.parts):
            return _blocked("the write tool may not edit Git internals")
    return 0


def _stop(event: dict[str, Any]) -> int:
    _append_log(event)
    completed = subprocess.run(
        [sys.executable, "scripts/validate_project.py", "--quick"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        print(completed.stdout, file=sys.stderr)
        print(completed.stderr, file=sys.stderr)
    return completed.returncode


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"context", "log", "guard", "stop"}:
        print("usage: project_hook.py {context|log|guard|stop}", file=sys.stderr)
        return 1
    action = sys.argv[1]
    event = _read_event()
    if action == "guard":
        return _guard(event)
    if event is None:
        return _blocked("hook event was missing or malformed")
    if action == "context":
        return _context(event)
    if action == "log":
        _append_log(event)
        return 0
    return _stop(event)


if __name__ == "__main__":
    raise SystemExit(main())
