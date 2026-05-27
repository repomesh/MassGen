"""Tests for the standalone Codex native hook script.

The Codex hook script runs as a subprocess invoked by Codex. It reads hook
payload and permission manifest files from the workspace `.codex/` directory
and returns JSON on stdout.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HOOK_SCRIPT = str(
    Path(__file__).parent.parent / "mcp_tools" / "native_hook_adapters" / "codex_hook_script.py",
)


def _run_hook_script(
    hook_dir: str,
    event: str,
    stdin_data: str = "{}",
) -> dict:
    """Invoke the hook script as a subprocess and return parsed JSON output."""
    result = subprocess.run(
        [sys.executable, HOOK_SCRIPT, "--hook-dir", hook_dir, "--event", event],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"Hook script failed: {result.stderr}"
    output = result.stdout.strip()
    if not output:
        return {}
    return json.loads(output)


class TestHookScriptNoPayload:
    """When no payload file exists, hook script should allow the turn to continue."""

    def test_returns_empty_for_post_tool_use(self, tmp_path: Path) -> None:
        result = _run_hook_script(str(tmp_path), "PostToolUse")
        assert result == {}

    def test_returns_empty_for_pre_tool_use(self, tmp_path: Path) -> None:
        result = _run_hook_script(str(tmp_path), "PreToolUse")
        assert result == {}

    def test_returns_empty_for_lifecycle_events(self, tmp_path: Path) -> None:
        for event_name in ("SessionStart", "UserPromptSubmit", "Stop"):
            assert _run_hook_script(str(tmp_path), event_name) == {}


class TestPostToolUsePayloadConsumption:
    """PostToolUse should consume the shared hook_post_tool_use.json payload."""

    def _write_payload(
        self,
        hook_dir: Path,
        *,
        content: str,
        tool_matcher: str = "*",
        expires_at: float | None = None,
    ) -> None:
        hook_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "inject": {"content": content, "strategy": "tool_result"},
            "tool_matcher": tool_matcher,
            "expires_at": expires_at or (time.time() + 30),
            "sequence": 1,
        }
        (hook_dir / "hook_post_tool_use.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_injects_additional_context_for_bash(self, tmp_path: Path) -> None:
        self._write_payload(tmp_path, content="Runtime update from peer")
        stdin = json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "pytest -q"},
                "tool_response": '{"stdout":"ok"}',
            },
        )
        result = _run_hook_script(str(tmp_path), "PostToolUse", stdin_data=stdin)
        assert result == {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "Runtime update from peer",
            },
        }

    def test_consumes_payload_after_successful_read(self, tmp_path: Path) -> None:
        self._write_payload(tmp_path, content="one-shot payload")
        stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        _run_hook_script(str(tmp_path), "PostToolUse", stdin_data=stdin)
        assert not (tmp_path / "hook_post_tool_use.json").exists()

    def test_leaves_payload_when_tool_matcher_does_not_match(self, tmp_path: Path) -> None:
        self._write_payload(tmp_path, content="for MCP only", tool_matcher="mcp__*")
        stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        result = _run_hook_script(str(tmp_path), "PostToolUse", stdin_data=stdin)
        assert result == {}
        assert (tmp_path / "hook_post_tool_use.json").exists()

    def test_expired_payload_returns_empty_and_cleans_up(self, tmp_path: Path) -> None:
        self._write_payload(
            tmp_path,
            content="expired",
            expires_at=time.time() - 1,
        )
        stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        result = _run_hook_script(str(tmp_path), "PostToolUse", stdin_data=stdin)
        assert result == {}
        assert not (tmp_path / "hook_post_tool_use.json").exists()


class TestPreToolUsePermissionManifest:
    """PreToolUse can deny Bash commands using a serialized permission manifest."""

    def _write_permission_manifest(
        self,
        hook_dir: Path,
        *,
        workspace: Path,
        writable: Path,
        readonly: Path,
        protected: Path | None = None,
    ) -> None:
        hook_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "workspace": str(workspace.resolve()),
            "managed_paths": [
                {
                    "path": str(workspace.resolve()),
                    "permission": "write",
                    "path_type": "workspace",
                    "is_file": False,
                },
                {
                    "path": str(writable.resolve()),
                    "permission": "write",
                    "path_type": "context",
                    "is_file": False,
                    "protected_paths": [str(protected.resolve())] if protected else [],
                },
                {
                    "path": str(readonly.resolve()),
                    "permission": "read",
                    "path_type": "context",
                    "is_file": False,
                },
            ],
        }
        (hook_dir / "permission_manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_denies_bash_write_to_readonly_context(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        writable = tmp_path / "writable"
        readonly = tmp_path / "readonly"
        for path in (workspace, writable, readonly):
            path.mkdir()

        self._write_permission_manifest(
            tmp_path,
            workspace=workspace,
            writable=writable,
            readonly=readonly,
        )
        stdin = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "echo hi > blocked.txt",
                    "cwd": str(readonly),
                },
            },
        )

        result = _run_hook_script(str(tmp_path), "PreToolUse", stdin_data=stdin)
        assert result["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "read-only context path" in result["hookSpecificOutput"]["permissionDecisionReason"]

    def test_denies_bash_write_to_nested_readonly_context_even_when_workspace_is_writable(self, tmp_path: Path) -> None:
        """More-specific read-only paths must override broader writable parents."""
        workspace = tmp_path / "workspace"
        writable = tmp_path / "writable"
        readonly = workspace / "readonly"
        for path in (workspace, writable, readonly):
            path.mkdir(parents=True)

        self._write_permission_manifest(
            tmp_path,
            workspace=workspace,
            writable=writable,
            readonly=readonly,
        )
        stdin = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "echo hi > notes.txt",
                    "cwd": str(readonly),
                },
            },
        )

        result = _run_hook_script(str(tmp_path), "PreToolUse", stdin_data=stdin)
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "read-only context path" in result["hookSpecificOutput"]["permissionDecisionReason"]

    def test_denies_bash_write_to_protected_path_inside_writable_context(self, tmp_path: Path) -> None:
        """Protected paths in a writable context must remain read-only."""
        workspace = tmp_path / "workspace"
        writable = tmp_path / "writable"
        protected = writable / "protected"
        readonly = tmp_path / "readonly"
        for path in (workspace, writable, protected, readonly):
            path.mkdir(parents=True)

        self._write_permission_manifest(
            tmp_path,
            workspace=workspace,
            writable=writable,
            readonly=readonly,
            protected=protected,
        )
        stdin = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "echo hi > notes.txt",
                    "cwd": str(protected),
                },
            },
        )

        result = _run_hook_script(str(tmp_path), "PreToolUse", stdin_data=stdin)
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "read-only context path" in result["hookSpecificOutput"]["permissionDecisionReason"]

    def test_allows_bash_write_inside_workspace(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        writable = tmp_path / "writable"
        readonly = tmp_path / "readonly"
        for path in (workspace, writable, readonly):
            path.mkdir()

        self._write_permission_manifest(
            tmp_path,
            workspace=workspace,
            writable=writable,
            readonly=readonly,
        )
        stdin = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "echo hi > allowed.txt",
                    "cwd": str(workspace),
                },
            },
        )

        result = _run_hook_script(str(tmp_path), "PreToolUse", stdin_data=stdin)
        assert result == {}
