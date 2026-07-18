from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = ROOT / ".kiro" / "hooks" / "project_hook.py"
SPEC = importlib.util.spec_from_file_location("project_hook", HOOK_PATH)
assert SPEC is not None and SPEC.loader is not None
project_hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(project_hook)


class GuardTests(unittest.TestCase):
    def run_guard(self, event: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(HOOK_PATH), "guard"],
            cwd=ROOT,
            input=json.dumps(event),
            capture_output=True,
            text=True,
            check=False,
        )

    def shell_event(self, command: str) -> dict[str, object]:
        return {
            "hook_event_name": "preToolUse",
            "tool_name": "shell",
            "tool_input": {"command": command},
        }

    def claude_bash_event(self, command: str) -> dict[str, object]:
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }

    def test_allows_expected_git_commands(self) -> None:
        commands = (
            "git status --short",
            "git.exe status --short",
            "git -C . status --short",
            "git add README.md",
            "git commit -m safe",
            "git checkout -b feature/example",
            "git branch -m old-name new-name",
            "git branch -c source copy",
        )
        for build_event in (self.shell_event, self.claude_bash_event):
            for command in commands:
                with self.subTest(command=command, tool_name=build_event(command)["tool_name"]):
                    result = self.run_guard(build_event(command))
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_blocks_disallowed_git_variants(self) -> None:
        commands = (
            "git push origin main",
            "git.exe push origin main",
            "git -C . push origin phase/test",
            "git reset --hard HEAD~1",
            "git clean --force -d",
            "git clean -fd",
            "git commit --amend",
            "git commit --no-verify -m unsafe",
            "git commit -n -m unsafe",
            "git add .",
            "git add -- .",
            "git add :/",
            "git add -A",
            "git add --all",
            "git branch -D feature/example",
            "git branch -f feature/example HEAD",
            "git branch -d -f feature/example",
            "git branch -df feature/example",
            "git branch --delete -f feature/example",
            "git branch --force --delete feature/example",
            "git branch -M old-name new-name",
            "git branch -C source forced-copy",
            "git restore -- .",
            "git restore .",
            "git checkout .",
        )
        for build_event in (self.shell_event, self.claude_bash_event):
            for command in commands:
                with self.subTest(command=command, tool_name=build_event(command)["tool_name"]):
                    result = self.run_guard(build_event(command))
                    self.assertEqual(result.returncode, 2, result.stderr)

    def test_write_tool_is_limited_to_workspace(self) -> None:
        variants = (
            ("write", "path"),
            ("Write", "file_path"),
            ("Edit", "file_path"),
        )
        for tool_name, field in variants:
            with self.subTest(tool_name=tool_name):
                inside = self.run_guard(
                    {
                        "hook_event_name": "preToolUse",
                        "tool_name": tool_name,
                        "tool_input": {field: "PROJECT_CONTEXT.md"},
                    }
                )
                self.assertEqual(inside.returncode, 0, inside.stderr)

                outside = self.run_guard(
                    {
                        "hook_event_name": "preToolUse",
                        "tool_name": tool_name,
                        "tool_input": {field: str(ROOT.parent / "outside.txt")},
                    }
                )
                self.assertEqual(outside.returncode, 2, outside.stderr)

    def test_covered_tools_fail_closed_on_malformed_input(self) -> None:
        for event in (
            {},
            {"tool_name": "shell"},
            {"tool_name": "write", "tool_input": {}},
            {"tool_name": "Bash"},
            {"tool_name": "Write", "tool_input": {}},
        ):
            with self.subTest(event=event):
                result = self.run_guard(event)
                self.assertEqual(result.returncode, 2, result.stderr)


class LoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_log_path = project_hook.LOG_PATH
        self.git_state = {
            "branch": "phase",
            "commit": "abcdef1",
            "dirty": True,
            "git_status": "ok",
        }

    def tearDown(self) -> None:
        project_hook.LOG_PATH = self.original_log_path

    def test_branch_categories_do_not_retain_names(self) -> None:
        cases = {
            "main": "main",
            "phase/00-foundation": "phase",
            "feature/report": "feature",
            "bugfix/customer-name": "other",
            "": "unknown",
        }
        for branch, expected in cases.items():
            with self.subTest(branch=branch):
                self.assertEqual(project_hook._branch_category(branch), expected)

    def test_accepts_claude_code_hook_event_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "events.jsonl"
            project_hook.LOG_PATH = log_path
            claude_event_names = (
                "SessionStart",
                "UserPromptSubmit",
                "PreToolUse",
                "PostToolUse",
                "Stop",
            )
            with patch.object(project_hook, "_git_state", return_value=self.git_state):
                for hook_event_name in claude_event_names:
                    with self.subTest(hook_event_name=hook_event_name):
                        project_hook._append_log(
                            {"hook_event_name": hook_event_name, "tool_name": "Bash"}
                        )
            records = [
                json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([record["event"] for record in records], list(claude_event_names))

    def test_log_contains_only_sanitized_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "events.jsonl"
            project_hook.LOG_PATH = log_path
            event = {
                "hook_event_name": "postToolUse",
                "tool_name": "write",
                "tool_input": {"path": "secret-path-must-not-appear"},
                "tool_response": "secret-response-must-not-appear",
            }
            with (
                patch.dict(os.environ, {"KIRO_SESSION_ID": "raw-session-must-not-appear"}),
                patch.object(project_hook, "_git_state", return_value=self.git_state),
            ):
                project_hook._append_log(event)

            raw = log_path.read_text(encoding="utf-8")
            record = json.loads(raw)
            self.assertEqual(set(record), project_hook.LOG_KEYS)
            self.assertNotIn("raw-session-must-not-appear", raw)
            self.assertNotIn("secret-path-must-not-appear", raw)
            self.assertNotIn("secret-response-must-not-appear", raw)
            self.assertEqual(record["branch"], "phase")

    def test_append_rejects_record_outside_privacy_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "events.jsonl"
            project_hook.LOG_PATH = log_path
            with patch.object(project_hook, "_git_state", return_value=self.git_state):
                with self.assertRaisesRegex(ValueError, "unsafe hook metadata"):
                    project_hook._append_log({"hook_event_name": "customer-secret"})
            self.assertFalse(log_path.exists())

    def test_legacy_raw_metadata_is_scrubbed_before_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "events.jsonl"
            project_hook.LOG_PATH = log_path
            log_path.write_text(
                json.dumps(
                    {
                        "session_id": "raw-session-id",
                        "branch": "phase/customer-secret",
                        "event": "stop",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.object(project_hook, "_git_state", return_value=self.git_state):
                project_hook._append_log({"hook_event_name": "stop"})
            raw = log_path.read_text(encoding="utf-8")
            self.assertNotIn("raw-session-id", raw)
            self.assertNotIn("customer-secret", raw)
            self.assertEqual(len(raw.splitlines()), 1)
            self.assertEqual(set(json.loads(raw)), project_hook.LOG_KEYS)

    def test_exact_key_log_with_unsafe_metadata_is_scrubbed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "events.jsonl"
            project_hook.LOG_PATH = log_path
            unsafe = {
                "timestamp": "not-a-timestamp",
                "session_id": "0123456789abcdef",
                "event": "customer-secret",
                "tool": "write",
                "branch": "phase",
                "commit": "none",
                "dirty": True,
                "git_status": "ok",
            }
            log_path.write_text(json.dumps(unsafe) + "\n", encoding="utf-8")
            with patch.object(project_hook, "_git_state", return_value=self.git_state):
                project_hook._append_log({"hook_event_name": "stop"})
            raw = log_path.read_text(encoding="utf-8")
            self.assertNotIn("customer-secret", raw)
            self.assertNotIn("not-a-timestamp", raw)
            self.assertEqual(len(raw.splitlines()), 1)
            self.assertTrue(project_hook._record_is_safe(json.loads(raw)))

    def test_log_rotates_at_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "events.jsonl"
            project_hook.LOG_PATH = log_path
            valid = {
                "timestamp": "2026-07-16T00:00:00+00:00",
                "session_id": "0123456789abcdef",
                "event": "stop",
                "tool": None,
                "branch": "phase",
                "commit": "none",
                "dirty": True,
                "git_status": "ok",
            }
            line = json.dumps(valid) + "\n"
            repetitions = project_hook.MAX_LOG_BYTES // len(line) + 1
            log_path.write_text(line * repetitions, encoding="utf-8")
            with patch.object(project_hook, "_git_state", return_value=self.git_state):
                project_hook._append_log({"hook_event_name": "stop"})
            self.assertTrue(log_path.with_suffix(".jsonl.1").is_file())
            self.assertLess(log_path.stat().st_size, project_hook.MAX_LOG_BYTES)


if __name__ == "__main__":
    unittest.main()
