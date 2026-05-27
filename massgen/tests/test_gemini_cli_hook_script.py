"""Tests for the standalone Gemini CLI hook script (subprocess).

The hook script runs as a subprocess invoked by Gemini CLI. It reads a
payload file written by the MassGen orchestrator and returns JSON on stdout.
These tests invoke it directly as a subprocess to verify end-to-end behavior.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HOOK_SCRIPT = str(
    Path(__file__).parent.parent / "mcp_tools" / "native_hook_adapters" / "gemini_cli_hook_script.py",
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
    """When no payload file exists, hook script should return empty dict (allow)."""

    def test_returns_empty_for_after_tool(self, tmp_path: Path) -> None:
        result = _run_hook_script(str(tmp_path), "AfterTool")
        assert result == {}

    def test_returns_empty_for_before_tool(self, tmp_path: Path) -> None:
        result = _run_hook_script(str(tmp_path), "BeforeTool")
        assert result == {}

    def test_handles_empty_stdin(self, tmp_path: Path) -> None:
        result = _run_hook_script(str(tmp_path), "AfterTool", stdin_data="")
        assert result == {}


class TestHookScriptAfterToolInjection:
    """AfterTool event with a valid payload should inject additionalContext."""

    def _write_payload(self, hook_dir: Path, content: str, event: str = "AfterTool") -> None:
        hook_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "inject": {"content": content, "strategy": "tool_result"},
            "event": event,
            "expires_at": time.time() + 30,
            "sequence": 1,
        }
        (hook_dir / "hook_payload.json").write_text(json.dumps(payload))

    def test_injects_additional_context(self, tmp_path: Path) -> None:
        self._write_payload(tmp_path, "Agent B answered: 42")
        result = _run_hook_script(str(tmp_path), "AfterTool")
        assert result == {
            "hookSpecificOutput": {
                "additionalContext": "Agent B answered: 42",
            },
        }

    def test_consumes_payload_file(self, tmp_path: Path) -> None:
        """After consumption, the payload file should be deleted."""
        self._write_payload(tmp_path, "content")
        _run_hook_script(str(tmp_path), "AfterTool")
        assert not (tmp_path / "hook_payload.json").exists()

    def test_second_invocation_returns_empty(self, tmp_path: Path) -> None:
        """Payload is single-use — second invocation should return empty."""
        self._write_payload(tmp_path, "one-shot content")
        first = _run_hook_script(str(tmp_path), "AfterTool")
        assert "additionalContext" in first["hookSpecificOutput"]

        second = _run_hook_script(str(tmp_path), "AfterTool")
        assert second == {}

    def test_large_content(self, tmp_path: Path) -> None:
        """Hook should handle large injection content."""
        large_content = "x" * 100_000
        self._write_payload(tmp_path, large_content)
        result = _run_hook_script(str(tmp_path), "AfterTool")
        assert result["hookSpecificOutput"]["additionalContext"] == large_content


class TestHookScriptBeforeToolInjection:
    """BeforeTool event with a valid payload should inject or deny."""

    def _write_payload(
        self,
        hook_dir: Path,
        content: str,
        strategy: str = "tool_result",
    ) -> None:
        hook_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "inject": {"content": content, "strategy": strategy},
            "event": "BeforeTool",
            "expires_at": time.time() + 30,
            "sequence": 1,
        }
        (hook_dir / "hook_payload.json").write_text(json.dumps(payload))

    def test_injects_context_with_tool_result_strategy(self, tmp_path: Path) -> None:
        self._write_payload(tmp_path, "context injection", strategy="tool_result")
        result = _run_hook_script(str(tmp_path), "BeforeTool")
        assert result == {"additionalContext": "context injection"}

    def test_deny_with_deny_strategy(self, tmp_path: Path) -> None:
        self._write_payload(tmp_path, "Permission denied: read-only path", strategy="deny")
        result = _run_hook_script(str(tmp_path), "BeforeTool")
        assert result["decision"] == "deny"
        assert "Permission denied" in result["reason"]


class TestHookScriptPermissionManifest:
    """BeforeTool can enforce sandbox rules from a serialized manifest."""

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
        (hook_dir / "permission_manifest.json").write_text(json.dumps(payload))

    def test_denies_read_outside_allowed_paths(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        writable = tmp_path / "writable"
        readonly = tmp_path / "readonly"
        outside = tmp_path / "outside"
        for path in (workspace, writable, readonly, outside):
            path.mkdir()

        self._write_permission_manifest(
            tmp_path,
            workspace=workspace,
            writable=writable,
            readonly=readonly,
        )
        stdin = json.dumps(
            {
                "toolName": "read_file",
                "toolArgs": {"path": str(outside / "secret.txt")},
            },
        )

        result = _run_hook_script(str(tmp_path), "BeforeTool", stdin_data=stdin)
        assert result["decision"] == "deny"
        assert "outside allowed directories" in result["reason"]

    def test_denies_read_outside_allowed_paths_with_current_gemini_schema(self, tmp_path: Path) -> None:
        """Current Gemini CLI sends tool_name/tool_input rather than toolName/toolArgs."""
        workspace = tmp_path / "workspace"
        writable = tmp_path / "writable"
        readonly = tmp_path / "readonly"
        outside = tmp_path / "outside"
        for path in (workspace, writable, readonly, outside):
            path.mkdir()

        self._write_permission_manifest(
            tmp_path,
            workspace=workspace,
            writable=writable,
            readonly=readonly,
        )
        stdin = json.dumps(
            {
                "tool_name": "read_file",
                "tool_input": {"file_path": str(outside / "secret.txt")},
            },
        )

        result = _run_hook_script(str(tmp_path), "BeforeTool", stdin_data=stdin)
        assert result["decision"] == "deny"
        assert "outside allowed directories" in result["reason"]

    def test_allows_write_to_writable_context(self, tmp_path: Path) -> None:
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
                "toolName": "write_file",
                "toolArgs": {"path": str(writable / "notes.txt")},
            },
        )

        result = _run_hook_script(str(tmp_path), "BeforeTool", stdin_data=stdin)
        assert result == {}

    def test_allows_write_to_workspace_with_current_gemini_schema(self, tmp_path: Path) -> None:
        """Current Gemini write_file calls can use tool_input + absolute_path."""
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
                "tool_name": "write_file",
                "tool_input": {"absolute_path": str(workspace / "notes.txt")},
            },
        )

        result = _run_hook_script(str(tmp_path), "BeforeTool", stdin_data=stdin)
        assert result == {}

    def test_denies_write_to_readonly_context(self, tmp_path: Path) -> None:
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
                "toolName": "write_file",
                "toolArgs": {"path": str(readonly / "notes.txt")},
            },
        )

        result = _run_hook_script(str(tmp_path), "BeforeTool", stdin_data=stdin)
        assert result["decision"] == "deny"
        assert "read-only context path" in result["reason"]

    def test_denies_write_to_protected_path_inside_writable_context(self, tmp_path: Path) -> None:
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
                "tool_name": "write_file",
                "tool_input": {"absolute_path": str(protected / "notes.txt")},
            },
        )

        result = _run_hook_script(str(tmp_path), "BeforeTool", stdin_data=stdin)
        assert result["decision"] == "deny"
        assert "read-only context path" in result["reason"]

    def test_denies_write_to_nested_readonly_context_even_when_workspace_is_writable(self, tmp_path: Path) -> None:
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
                "tool_name": "write_file",
                "tool_input": {"absolute_path": str(readonly / "notes.txt")},
            },
        )

        result = _run_hook_script(str(tmp_path), "BeforeTool", stdin_data=stdin)
        assert result["decision"] == "deny"
        assert "read-only context path" in result["reason"]

    def test_denies_shell_write_when_dir_path_is_outside_allowed_paths(self, tmp_path: Path) -> None:
        """Shell tools often provide a dir_path with a relative command target."""
        workspace = tmp_path / "workspace"
        writable = tmp_path / "writable"
        readonly = tmp_path / "readonly"
        outside = tmp_path / "outside"
        for path in (workspace, writable, readonly, outside):
            path.mkdir()

        self._write_permission_manifest(
            tmp_path,
            workspace=workspace,
            writable=writable,
            readonly=readonly,
        )
        stdin = json.dumps(
            {
                "tool_name": "run_shell_command",
                "tool_input": {
                    "command": "echo 'test content' > bash_output.txt",
                    "dir_path": str(outside),
                },
            },
        )

        result = _run_hook_script(str(tmp_path), "BeforeTool", stdin_data=stdin)
        assert result["decision"] == "deny"
        assert str(outside) in result["reason"]

    def test_denies_shell_write_when_directory_is_outside_allowed_paths(self, tmp_path: Path) -> None:
        """Current Gemini shell docs use `directory` for the working directory."""
        workspace = tmp_path / "workspace"
        writable = tmp_path / "writable"
        readonly = tmp_path / "readonly"
        outside = tmp_path / "outside"
        for path in (workspace, writable, readonly, outside):
            path.mkdir()

        self._write_permission_manifest(
            tmp_path,
            workspace=workspace,
            writable=writable,
            readonly=readonly,
        )
        stdin = json.dumps(
            {
                "tool_name": "run_shell_command",
                "tool_input": {
                    "command": "echo 'test content' > bash_output.txt",
                    "directory": "../outside",
                },
            },
        )

        result = _run_hook_script(str(tmp_path), "BeforeTool", stdin_data=stdin)
        assert result["decision"] == "deny"
        assert str(outside) in result["reason"]

    def test_denies_shell_read_when_directory_is_outside_allowed_paths(self, tmp_path: Path) -> None:
        """Read commands with a relative target should still be blocked by directory scope."""
        workspace = tmp_path / "workspace"
        writable = tmp_path / "writable"
        readonly = tmp_path / "readonly"
        outside = tmp_path / "outside"
        for path in (workspace, writable, readonly, outside):
            path.mkdir()

        self._write_permission_manifest(
            tmp_path,
            workspace=workspace,
            writable=writable,
            readonly=readonly,
        )
        stdin = json.dumps(
            {
                "tool_name": "run_shell_command",
                "tool_input": {
                    "command": "cat data.txt",
                    "directory": str(outside),
                },
            },
        )

        result = _run_hook_script(str(tmp_path), "BeforeTool", stdin_data=stdin)
        assert result["decision"] == "deny"
        assert str(outside) in result["reason"]

    def test_denies_list_directory_outside_with_current_gemini_schema(self, tmp_path: Path) -> None:
        """Directory listing tools should be treated as read-like operations."""
        workspace = tmp_path / "workspace"
        writable = tmp_path / "writable"
        readonly = tmp_path / "readonly"
        outside = tmp_path / "outside"
        for path in (workspace, writable, readonly, outside):
            path.mkdir()

        self._write_permission_manifest(
            tmp_path,
            workspace=workspace,
            writable=writable,
            readonly=readonly,
        )
        stdin = json.dumps(
            {
                "tool_name": "list_directory",
                "tool_input": {"absolute_path": str(outside)},
            },
        )

        result = _run_hook_script(str(tmp_path), "BeforeTool", stdin_data=stdin)
        assert result["decision"] == "deny"
        assert "outside allowed directories" in result["reason"]

    def test_denies_read_many_files_outside_allowed_paths(self, tmp_path: Path) -> None:
        """Batch read tools may pass a `paths` list instead of a single file path."""
        workspace = tmp_path / "workspace"
        writable = tmp_path / "writable"
        readonly = tmp_path / "readonly"
        outside = tmp_path / "outside"
        for path in (workspace, writable, readonly, outside):
            path.mkdir()

        self._write_permission_manifest(
            tmp_path,
            workspace=workspace,
            writable=writable,
            readonly=readonly,
        )
        stdin = json.dumps(
            {
                "tool_name": "read_many_files",
                "tool_input": {
                    "paths": [str(outside / "secret.txt")],
                },
            },
        )

        result = _run_hook_script(str(tmp_path), "BeforeTool", stdin_data=stdin)
        assert result["decision"] == "deny"
        assert "outside allowed directories" in result["reason"]


class TestHookScriptExpiry:
    """Expired payloads should be cleaned up and treated as no-op."""

    def test_expired_payload_returns_empty(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        payload = {
            "inject": {"content": "should not appear", "strategy": "tool_result"},
            "event": "AfterTool",
            "expires_at": time.time() - 10,  # Expired 10 seconds ago
            "sequence": 1,
        }
        (tmp_path / "hook_payload.json").write_text(json.dumps(payload))

        result = _run_hook_script(str(tmp_path), "AfterTool")
        assert result == {}

    def test_expired_payload_cleans_up_file(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        payload = {
            "inject": {"content": "expired", "strategy": "tool_result"},
            "event": "AfterTool",
            "expires_at": time.time() - 1,
            "sequence": 1,
        }
        (tmp_path / "hook_payload.json").write_text(json.dumps(payload))

        _run_hook_script(str(tmp_path), "AfterTool")
        assert not (tmp_path / "hook_payload.json").exists()


class TestHookScriptEventMismatch:
    """Payloads for wrong event type should be ignored (not consumed)."""

    def test_after_tool_payload_not_consumed_by_before_tool(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        payload = {
            "inject": {"content": "for AfterTool", "strategy": "tool_result"},
            "event": "AfterTool",
            "expires_at": time.time() + 30,
            "sequence": 1,
        }
        (tmp_path / "hook_payload.json").write_text(json.dumps(payload))

        result = _run_hook_script(str(tmp_path), "BeforeTool")
        assert result == {}
        # File should NOT be consumed — it's for a different event
        assert (tmp_path / "hook_payload.json").exists()

    def test_before_tool_payload_not_consumed_by_after_tool(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        payload = {
            "inject": {"content": "for BeforeTool", "strategy": "deny"},
            "event": "BeforeTool",
            "expires_at": time.time() + 30,
            "sequence": 1,
        }
        (tmp_path / "hook_payload.json").write_text(json.dumps(payload))

        result = _run_hook_script(str(tmp_path), "AfterTool")
        assert result == {}
        assert (tmp_path / "hook_payload.json").exists()


class TestHookScriptMalformedPayload:
    """Malformed payload files should not crash the hook — just allow."""

    def test_invalid_json_returns_empty(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "hook_payload.json").write_text("not valid json {{")

        result = _run_hook_script(str(tmp_path), "AfterTool")
        assert result == {}

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "hook_payload.json").write_text("")

        result = _run_hook_script(str(tmp_path), "AfterTool")
        assert result == {}

    def test_missing_inject_key_returns_empty(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "hook_payload.json").write_text(json.dumps({"event": "AfterTool"}))

        result = _run_hook_script(str(tmp_path), "AfterTool")
        assert result == {}


class TestHookScriptStdinHandling:
    """Hook script should handle various stdin formats gracefully."""

    def test_valid_tool_event_on_stdin(self, tmp_path: Path) -> None:
        """Real Gemini CLI sends tool event data on stdin."""
        stdin = json.dumps(
            {
                "toolName": "read_file",
                "toolArgs": {"path": "test.txt"},
                "toolResult": "file contents",
            },
        )
        result = _run_hook_script(str(tmp_path), "AfterTool", stdin_data=stdin)
        assert result == {}

    def test_invalid_json_stdin_doesnt_crash(self, tmp_path: Path) -> None:
        result = _run_hook_script(str(tmp_path), "AfterTool", stdin_data="broken {json")
        assert result == {}
