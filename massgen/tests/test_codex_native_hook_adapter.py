"""Tests for Codex native hook adapter and workspace hook config writing."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    import tomllib
except ImportError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib

from massgen.mcp_tools.hooks import (
    GeneralHookManager,
    HookResult,
    HookType,
    PatternHook,
)


class _AllowHook(PatternHook):
    async def execute(self, function_name, arguments, context=None, **kwargs):
        return HookResult.allow()


@pytest.fixture(autouse=True)
def _mock_codex_cli(monkeypatch):
    from massgen.backend.codex import CodexBackend

    monkeypatch.setattr(CodexBackend, "_find_codex_cli", lambda self: "/usr/bin/codex")
    monkeypatch.setattr(CodexBackend, "_has_cached_credentials", lambda self: True)


def _read_workspace_codex_config(workspace: Path) -> dict:
    config_path = workspace / ".codex" / "config.toml"
    return tomllib.loads(config_path.read_text(encoding="utf-8"))


class TestCodexNativeHookAdapter:
    def test_supports_post_tool_use_only(self, tmp_path: Path) -> None:
        from massgen.mcp_tools.native_hook_adapters.codex_adapter import (
            CodexNativeHookAdapter,
        )

        adapter = CodexNativeHookAdapter(hook_dir=tmp_path)
        assert adapter.supports_hook_type(HookType.PRE_TOOL_USE) is False
        assert adapter.supports_hook_type(HookType.POST_TOOL_USE) is True

    def test_builds_hooks_json_shape(self, tmp_path: Path) -> None:
        from massgen.mcp_tools.native_hook_adapters.codex_adapter import (
            CodexNativeHookAdapter,
        )

        adapter = CodexNativeHookAdapter(hook_dir=tmp_path)
        manager = GeneralHookManager()
        manager.register_global_hook(HookType.POST_TOOL_USE, _AllowHook(name="bridge", matcher="Bash"))

        config = adapter.build_native_hooks_config(manager)

        assert "hooks" in config
        assert "PostToolUse" in config["hooks"]
        entry = config["hooks"]["PostToolUse"][0]
        assert entry["matcher"] == "Bash"
        assert entry["hooks"][0]["type"] == "command"
        assert "--event PostToolUse" in entry["hooks"][0]["command"]

    def test_ignores_pre_tool_hooks_when_building_native_config(self, tmp_path: Path) -> None:
        from massgen.mcp_tools.native_hook_adapters.codex_adapter import (
            CodexNativeHookAdapter,
        )

        adapter = CodexNativeHookAdapter(hook_dir=tmp_path)
        manager = GeneralHookManager()
        manager.register_global_hook(HookType.PRE_TOOL_USE, _AllowHook(name="permission", matcher="Bash"))
        manager.register_global_hook(HookType.POST_TOOL_USE, _AllowHook(name="bridge", matcher="Bash"))

        config = adapter.build_native_hooks_config(manager)

        assert "hooks" in config
        assert "PreToolUse" not in config["hooks"]
        assert "PostToolUse" in config["hooks"]

    def test_merge_native_configs_accumulates_events(self, tmp_path: Path) -> None:
        from massgen.mcp_tools.native_hook_adapters.codex_adapter import (
            CodexNativeHookAdapter,
        )

        adapter = CodexNativeHookAdapter(hook_dir=tmp_path)
        merged = adapter.merge_native_configs(
            {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "pre"}]}]}},
            {"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "post"}]}]}},
        )

        assert "PreToolUse" in merged["hooks"]
        assert "PostToolUse" in merged["hooks"]


class TestCodexBackendNativeHookConfig:
    def test_backend_supports_both_native_and_mcp_hooks(self, tmp_path: Path) -> None:
        from massgen.backend.codex import CodexBackend

        backend = CodexBackend(cwd=str(tmp_path))
        assert backend.supports_native_hooks() is True
        assert backend.supports_mcp_server_hooks() is True

    def test_writes_hooks_json_and_feature_flag_when_native_hooks_config_set(self, tmp_path: Path) -> None:
        from massgen.backend.codex import CodexBackend
        from massgen.mcp_tools.native_hook_adapters.codex_adapter import (
            CodexNativeHookAdapter,
        )

        backend = CodexBackend(cwd=str(tmp_path))
        adapter = CodexNativeHookAdapter(hook_dir=tmp_path / ".codex")
        manager = GeneralHookManager()
        manager.register_global_hook(HookType.POST_TOOL_USE, _AllowHook(name="bridge", matcher="Bash"))
        backend.set_native_hooks_config(adapter.build_native_hooks_config(manager))

        backend._write_workspace_config()

        config = _read_workspace_codex_config(tmp_path)
        assert config["features"]["codex_hooks"] is True

        hooks_path = tmp_path / ".codex" / "hooks.json"
        assert hooks_path.exists()
        hooks_config = json.loads(hooks_path.read_text(encoding="utf-8"))
        assert "PostToolUse" in hooks_config["hooks"]

    def test_does_not_write_permission_manifest_or_pre_tool_hook(self, tmp_path: Path) -> None:
        from massgen.backend.codex import CodexBackend

        workspace = tmp_path
        readonly = tmp_path / "readonly"
        readonly.mkdir()
        backend = CodexBackend(cwd=str(workspace))
        backend.filesystem_manager = SimpleNamespace(
            path_permission_manager=SimpleNamespace(
                managed_paths=[
                    SimpleNamespace(
                        path=workspace,
                        permission=SimpleNamespace(value="write"),
                        path_type="workspace",
                        is_file=False,
                        protected_paths=[],
                    ),
                    SimpleNamespace(
                        path=readonly,
                        permission=SimpleNamespace(value="read"),
                        path_type="context",
                        is_file=False,
                        protected_paths=[],
                    ),
                ],
            ),
            get_current_workspace=lambda: workspace,
        )

        backend._write_workspace_config()

        manifest_path = workspace / ".codex" / "permission_manifest.json"
        assert manifest_path.exists() is False

        hooks_path = workspace / ".codex" / "hooks.json"
        assert hooks_path.exists() is False


class TestCodexWorkspaceApprovalPolicy:
    """Regression: codex 0.124+ rejects shell-tool approvals when
    approval_policy isn't "never" (deprecated "on-failure" default). MassGen
    always runs codex non-interactively via `codex exec --full-auto`, so the
    workspace config must set approval_policy explicitly. External MCP tools
    also need their server-level approval mode set to "approve" because they
    use a separate approval gate.
    """

    def test_full_auto_writes_approval_policy_never(self, tmp_path: Path) -> None:
        from massgen.backend.codex import CodexBackend

        backend = CodexBackend(cwd=str(tmp_path), approval_mode="full-auto")
        backend._write_workspace_config()

        config = _read_workspace_codex_config(tmp_path)
        assert config.get("approval_policy") == "never"

    def test_mcp_servers_default_to_approved_tools_in_non_interactive_runs(self, tmp_path: Path) -> None:
        """codex exec cannot answer MCP approval prompts, so MassGen-written
        MCP servers must bypass the MCP-specific approval gate too."""
        from massgen.backend.codex import CodexBackend

        backend = CodexBackend(
            cwd=str(tmp_path),
            approval_mode="full-auto",
            mcp_servers=[
                {
                    "name": "planning_test",
                    "type": "stdio",
                    "command": "fastmcp",
                    "args": ["run", "planning.py:create_server"],
                    "tool_timeout_sec": 120,
                },
            ],
        )
        backend._write_workspace_config()

        config = _read_workspace_codex_config(tmp_path)
        server_config = config["mcp_servers"]["planning_test"]
        assert config.get("approval_policy") == "never"
        assert server_config["default_tools_approval_mode"] == "approve"

    def test_auto_edit_writes_approval_policy_never(self, tmp_path: Path) -> None:
        from massgen.backend.codex import CodexBackend

        backend = CodexBackend(cwd=str(tmp_path), approval_mode="auto-edit")
        backend._write_workspace_config()

        config = _read_workspace_codex_config(tmp_path)
        assert config.get("approval_policy") == "never"

    def test_full_access_writes_approval_policy_never(self, tmp_path: Path) -> None:
        from massgen.backend.codex import CodexBackend

        backend = CodexBackend(cwd=str(tmp_path), approval_mode="full-access")
        backend._write_workspace_config()

        config = _read_workspace_codex_config(tmp_path)
        assert config.get("approval_policy") == "never"

    def test_dangerous_no_sandbox_does_not_force_approval_policy(self, tmp_path: Path) -> None:
        """dangerous-no-sandbox passes --dangerously-bypass-approvals-and-sandbox
        which already short-circuits approval; no need to set approval_policy."""
        from massgen.backend.codex import CodexBackend

        backend = CodexBackend(cwd=str(tmp_path), approval_mode="dangerous-no-sandbox")
        backend._write_workspace_config()

        config = _read_workspace_codex_config(tmp_path)
        assert "approval_policy" not in config
