"""Tests for Antigravity CLI backend.

The Antigravity CLI (`agy`, Google's successor to the Gemini CLI as of I/O 2026)
is architecturally simpler than the Gemini CLI: plain text stdout, no
stream-json events, no per-invocation --model flag. These tests pin the
contract MassGen depends on.

Run with: uv run pytest massgen/tests/test_antigravity_cli_backend.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from massgen.backend.antigravity_cli import (
    AGY_DEFAULT_MODEL_LABEL,
    AntigravityCLIBackend,
)


@pytest.fixture
def backend(tmp_path):
    """AntigravityCLIBackend with binary mocked and cwd in a temp dir."""
    with patch.object(AntigravityCLIBackend, "_find_agy_cli", return_value="/fake/bin/agy"):
        return AntigravityCLIBackend(cwd=str(tmp_path))


class TestBinaryDiscovery:
    """The backend must locate the `agy` binary; refuse to construct otherwise."""

    def test_find_agy_cli_returns_path_on_path(self, tmp_path):
        fake_bin = tmp_path / "agy"
        fake_bin.write_text("")
        fake_bin.chmod(0o755)
        with patch("shutil.which", return_value=str(fake_bin)):
            assert AntigravityCLIBackend._find_agy_cli() == str(fake_bin)

    def test_find_agy_cli_returns_local_bin_fallback(self, monkeypatch, tmp_path):
        # No `agy` on PATH, but installer-default location exists
        with patch("shutil.which", return_value=None):
            home = tmp_path
            agy_path = home / ".local" / "bin" / "agy"
            agy_path.parent.mkdir(parents=True)
            agy_path.write_text("")
            agy_path.chmod(0o755)
            monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
            assert AntigravityCLIBackend._find_agy_cli() == str(agy_path)

    def test_construct_raises_when_binary_missing(self):
        with patch.object(AntigravityCLIBackend, "_find_agy_cli", return_value=None):
            with pytest.raises(RuntimeError, match="install.sh"):
                AntigravityCLIBackend()


class TestCommandConstruction:
    """The backend invokes `agy` with the right flags for our use cases."""

    def test_minimal_command_uses_print_mode_with_yolo(self, backend):
        cmd = backend._build_exec_command("hello")
        assert cmd[0] == "/fake/bin/agy"
        # -p drives non-interactive mode; the prompt comes after the flag
        assert "-p" in cmd
        # `--dangerously-skip-permissions` is the agy equivalent of `--approval-mode yolo`
        assert "--dangerously-skip-permissions" in cmd
        # The user prompt must end up as a real arg, not interpolated
        assert "hello" in cmd

    def test_command_never_emits_conversation_or_continue_flags(self, backend):
        # Each MassGen call is a single-shot `-p` invocation; the orchestrator
        # already replays prior-response context in retry prompts, so agy-side
        # session resumption is unnecessary (and `--conversation` with a UUID
        # we generated fails with "conversation X not found" since agy assigns
        # its own IDs). The backend must never emit these flags.
        cmd = backend._build_exec_command("again")
        assert "--conversation" not in cmd
        assert "--continue" not in cmd
        assert "-c" not in cmd

    def test_command_passes_gemini_dir_for_workspace_isolation(self, backend, tmp_path):
        # agy honors a hidden `--gemini_dir <abs_path>` flag (verified via binary
        # strings + live test). We use it so each session gets an isolated config
        # root and never mutates the user's ~/.gemini/.
        backend._config_cwd = str(tmp_path / "cwd")
        cmd = backend._build_exec_command("hello")
        assert any(arg.startswith("--gemini_dir") for arg in cmd), f"--gemini_dir flag missing from: {cmd}"
        # Path arg must be absolute (agy logs reject relative: ".gemini must be an absolute path")
        gd_index = next(i for i, a in enumerate(cmd) if a == "--gemini_dir" or a.startswith("--gemini_dir="))
        if cmd[gd_index] == "--gemini_dir":
            path_arg = cmd[gd_index + 1]
        else:
            path_arg = cmd[gd_index].split("=", 1)[1]
        assert Path(path_arg).is_absolute(), f"--gemini_dir path must be absolute, got {path_arg!r}"
        assert ".antigravity" in path_arg

    def test_command_passes_log_file_for_error_surfacing(self, backend, tmp_path):
        # agy exits 0 with empty stdout on quota/auth failures. We capture
        # `--log-file` so silent failures can be surfaced as real errors.
        backend._config_cwd = str(tmp_path / "cwd")
        cmd = backend._build_exec_command("hello")
        assert "--log-file" in cmd, f"--log-file flag missing from: {cmd}"
        idx = cmd.index("--log-file")
        log_path = cmd[idx + 1]
        assert Path(log_path).is_absolute()
        assert ".antigravity" in log_path

    def test_command_does_not_pass_model_flag(self, backend):
        """agy 1.0.0 has no --model flag; we must not emit one even when configured."""
        backend.model = "gemini-3-flash-preview"
        cmd = backend._build_exec_command("hello")
        assert "--model" not in cmd
        assert "-m" not in cmd


class TestMCPConfigEmission:
    """MCP server entries must use Antigravity's schema (serverUrl, not url)."""

    def test_http_server_emits_serverUrl_not_url(self, backend):
        backend.mcp_servers = [
            {
                "name": "remote_thing",
                "url": "https://api.example.com/mcp/",
                "headers": {"Authorization": "Bearer X"},
            },
        ]
        cfg = backend._build_mcp_config_dict()
        assert "remote_thing" in cfg
        entry = cfg["remote_thing"]
        assert entry.get("serverUrl") == "https://api.example.com/mcp/"
        assert "url" not in entry
        assert entry.get("headers") == {"Authorization": "Bearer X"}

    def test_stdio_server_emits_command_args_env(self, backend):
        backend.mcp_servers = [
            {
                "name": "local_thing",
                "command": "node",
                "args": ["/path/to/server.js"],
                "env": {"FOO": "bar"},
            },
        ]
        cfg = backend._build_mcp_config_dict()
        entry = cfg["local_thing"]
        assert entry["command"] == "node"
        assert entry["args"] == ["/path/to/server.js"]
        assert entry["env"] == {"FOO": "bar"}
        assert "serverUrl" not in entry

    def test_servers_passed_as_dict_map_are_accepted(self, backend):
        """Some config schemas pass mcp_servers as a name-keyed dict, not a list."""
        backend.config["mcp_servers"] = {
            "alpha": {"command": "alpha-bin"},
            "beta": {"url": "https://beta.example.com/"},
        }
        cfg = backend._build_mcp_config_dict()
        assert cfg["alpha"]["command"] == "alpha-bin"
        assert cfg["beta"]["serverUrl"] == "https://beta.example.com/"
        assert "url" not in cfg["beta"]

    def test_empty_servers_returns_empty_dict(self, backend):
        backend.mcp_servers = []
        cfg = backend._build_mcp_config_dict()
        assert cfg == {}


class TestMCPConfigFile:
    """The backend writes mcp_config.json to a workspace-local `.antigravity/config/` dir
    that agy reads via `--gemini_dir`. The user's global ~/.gemini/ is never touched."""

    def test_write_mcp_config_writes_to_workspace_gemini_dir(self, tmp_path):
        # No monkeypatching needed — the path is derived from cwd, not a module global.
        with patch.object(AntigravityCLIBackend, "_find_agy_cli", return_value="/fake/agy"):
            be = AntigravityCLIBackend(cwd=str(tmp_path / "cwd"))
            be.mcp_servers = [{"name": "only_one", "command": "/x"}]
            be._write_mcp_config()

            expected = be._workspace_config_dir() / "config" / "mcp_config.json"
            assert expected.exists(), f"expected workspace-local mcp_config at {expected}"
            written = json.loads(expected.read_text())
            assert "only_one" in written["mcpServers"]

    def test_write_mcp_config_does_not_touch_user_global_file(self, tmp_path, monkeypatch):
        # Sentinel: place a marker at the *old* user-global path; assert it's untouched.
        # We do this by pointing AGY_MCP_CONFIG_PATH at a tmp file we control.
        sentinel = tmp_path / "sentinel_global_mcp.json"
        sentinel.write_text('{"mcpServers": {"user_only": {"command": "/u"}}}')
        monkeypatch.setattr(
            "massgen.backend.antigravity_cli.AGY_MCP_CONFIG_PATH",
            sentinel,
        )
        with patch.object(AntigravityCLIBackend, "_find_agy_cli", return_value="/fake/agy"):
            be = AntigravityCLIBackend(cwd=str(tmp_path / "cwd"))
            be.mcp_servers = [{"name": "mine", "command": "/m"}]
            be._write_mcp_config()
            be._restore_mcp_config()

            after = json.loads(sentinel.read_text())
            assert after == {"mcpServers": {"user_only": {"command": "/u"}}}, "user-global mcp_config.json must remain untouched"

    def test_default_mcp_path_constant_preserved_for_compat(self):
        # The module-level constant still exists for backward compat / introspection
        # but is no longer the active write target.
        from massgen.backend.antigravity_cli import AGY_MCP_CONFIG_PATH

        assert AGY_MCP_CONFIG_PATH == Path.home() / ".gemini" / "config" / "mcp_config.json"

    def test_workspace_mcp_path_is_isolated_per_cwd(self, tmp_path):
        """Each backend instance writes to its own cwd-scoped mcp_config.json."""
        with patch.object(AntigravityCLIBackend, "_find_agy_cli", return_value="/fake/agy"):
            be_a = AntigravityCLIBackend(cwd=str(tmp_path / "a"))
            be_b = AntigravityCLIBackend(cwd=str(tmp_path / "b"))
            assert be_a._workspace_mcp_config_path() != be_b._workspace_mcp_config_path()
            for be in (be_a, be_b):
                assert be._workspace_mcp_config_path().is_absolute()


class TestAgentIdNotCollidingWithGeminiCli:
    """Custom-tools wiring must use the antigravity_cli identifier so coordination
    across mixed-backend runs (gemini_cli + antigravity_cli) stays distinguishable."""

    def test_agent_id_for_custom_tools_is_antigravity_cli(self, backend):
        # Probe via the module-level constant the implementation should expose
        from massgen.backend.antigravity_cli import AGY_AGENT_ID_LITERAL

        assert AGY_AGENT_ID_LITERAL == "antigravity_cli"


class TestProviderMetadata:
    """Backend identity surfaces correctly to the orchestrator."""

    def test_provider_name(self, backend):
        assert backend.get_provider_name() == "Antigravity CLI"

    def test_filesystem_support_is_native(self, backend):
        from massgen.backend.base import FilesystemSupport

        assert backend.get_filesystem_support() == FilesystemSupport.NATIVE

    def test_default_model_label_is_gemini_3_flash(self):
        # agy server-selects the model; we expose a label only for UI/logging.
        assert "flash" in AGY_DEFAULT_MODEL_LABEL.lower()


class TestStdoutStreamingParser:
    """Plain-text stdout lines become content chunks; clean exit yields done."""

    @pytest.mark.asyncio
    async def test_stdout_lines_yield_content_chunks(self, backend):
        from massgen.backend.base import StreamChunk

        proc_mock = AsyncMock()

        async def _aiter_stdout():
            for line in (b"hello\n", b"world\n"):
                yield line

        proc_mock.stdout = _aiter_stdout()
        proc_mock.wait = AsyncMock(return_value=0)
        proc_mock.returncode = 0

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc_mock)):
            chunks = []
            async for chunk in backend._stream_local("hi"):
                chunks.append(chunk)

        contents = [c for c in chunks if c.type == "content"]
        done = [c for c in chunks if c.type == "done"]
        assert any("hello" in (c.content or "") for c in contents)
        assert any("world" in (c.content or "") for c in contents)
        assert len(done) == 1
        assert isinstance(done[0], StreamChunk)

    @pytest.mark.asyncio
    async def test_nonzero_exit_yields_error_chunk(self, backend):
        proc_mock = AsyncMock()

        async def _aiter_stdout():
            yield b"some warning text\n"

        proc_mock.stdout = _aiter_stdout()
        proc_mock.wait = AsyncMock(return_value=2)
        proc_mock.returncode = 2

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc_mock)):
            chunks = []
            async for chunk in backend._stream_local("hi"):
                chunks.append(chunk)

        errors = [c for c in chunks if c.type == "error"]
        assert len(errors) == 1
        assert "agy" in (errors[0].error or "").lower() or "exit" in (errors[0].error or "").lower()

    @pytest.mark.asyncio
    async def test_silent_quota_failure_is_surfaced_from_log_file(self, backend, tmp_path):
        # agy exits 0 with empty stdout on RESOURCE_EXHAUSTED. The backend
        # must scan the --log-file we pass and surface the real error so the
        # orchestrator stops retry-looping against an empty response.
        backend._config_cwd = str(tmp_path / "cwd")
        log_path = backend._agy_log_file_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "I0520 09:23:29 server.go:1072 Sending user message\n" "E0520 09:23:30 log.go:398] agent executor error: RESOURCE_EXHAUSTED (code 429): Individual quota reached. Resets in 3h0m45s.\n",
            encoding="utf-8",
        )

        proc_mock = AsyncMock()

        async def _aiter_stdout():
            return
            yield  # pragma: no cover — empty generator

        proc_mock.stdout = _aiter_stdout()
        proc_mock.wait = AsyncMock(return_value=0)
        proc_mock.returncode = 0

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc_mock)):
            chunks = []
            async for chunk in backend._stream_local("hi"):
                chunks.append(chunk)

        errors = [c for c in chunks if c.type == "error"]
        contents = [c for c in chunks if c.type == "content"]
        assert errors, "silent agy failure must yield an error chunk"
        assert any("quota" in (c.error or "").lower() or "429" in (c.error or "") for c in errors)
        # User-visible content chunk should also flag the failure so the TUI
        # shows what happened instead of an empty agent panel.
        assert any("Antigravity CLI ERROR" in (c.content or "") for c in contents)


class TestWorkflowToolTextFallback:
    """When MassGen orchestrator passes vote/new_answer tools, agy can't expose
    them as native MCP tools — agy 1.0.0 doesn't load MCP tools per invocation.
    The backend MUST inject formatting instructions into the prompt and parse
    the agent's text response for workflow tool calls."""

    @staticmethod
    def _workflow_tools():
        return [
            {
                "type": "function",
                "function": {
                    "name": "new_answer",
                    "description": "Submit a candidate answer.",
                    "parameters": {
                        "type": "object",
                        "properties": {"content": {"type": "string"}},
                        "required": ["content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "vote",
                    "description": "Vote for the best answer.",
                    "parameters": {
                        "type": "object",
                        "properties": {"agent_id": {"type": "string"}, "reason": {"type": "string"}},
                        "required": ["agent_id", "reason"],
                    },
                },
            },
        ]

    @pytest.mark.asyncio
    async def test_prompt_contains_workflow_instructions_when_workflow_tools_present(self, backend):
        """Workflow tool definitions must produce inline text-fallback instructions."""
        captured_cmd = {}
        proc_mock = AsyncMock()

        async def _aiter_stdout():
            for line in (b'{"tool_name": "new_answer", "arguments": {"content": "42"}}\n',):
                yield line

        proc_mock.stdout = _aiter_stdout()
        proc_mock.wait = AsyncMock(return_value=0)
        proc_mock.returncode = 0

        async def fake_exec(*args, **kwargs):
            captured_cmd["cmd"] = list(args)
            return proc_mock

        with patch("asyncio.create_subprocess_exec", new=fake_exec):
            chunks = []
            async for chunk in backend.stream_with_tools(
                messages=[{"role": "user", "content": "what is 2+2?"}],
                tools=self._workflow_tools(),
            ):
                chunks.append(chunk)

        cmd = captured_cmd["cmd"]
        # The prompt is the LAST argument after `-p`. Inspect it.
        assert "-p" in cmd, f"missing -p flag in {cmd!r}"
        prompt_arg = cmd[cmd.index("-p") + 1]
        # The injection must teach the agent how to format workflow tool calls.
        # We don't pin the exact wording — just that it references the workflow
        # tools and the JSON structure the orchestrator parses.
        assert "new_answer" in prompt_arg, "workflow tool 'new_answer' not in prompt"
        assert "vote" in prompt_arg, "workflow tool 'vote' not in prompt"
        assert "tool_name" in prompt_arg, "JSON formatting hint missing from prompt"

    @pytest.mark.asyncio
    async def test_stdout_workflow_json_yields_tool_calls_chunk(self, backend):
        """When agy emits a workflow JSON envelope on stdout, the backend must
        emit a `StreamChunk(type="tool_calls")` so the orchestrator can act."""
        proc_mock = AsyncMock()

        async def _aiter_stdout():
            for line in (
                b"Here is my answer.\n",
                b'{"tool_name": "new_answer", "arguments": {"content": "42 is the answer"}}\n',
            ):
                yield line

        proc_mock.stdout = _aiter_stdout()
        proc_mock.wait = AsyncMock(return_value=0)
        proc_mock.returncode = 0

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc_mock)):
            chunks = []
            async for chunk in backend.stream_with_tools(
                messages=[{"role": "user", "content": "what is 2+2?"}],
                tools=self._workflow_tools(),
            ):
                chunks.append(chunk)

        tool_call_chunks = [c for c in chunks if c.type == "tool_calls"]
        assert len(tool_call_chunks) == 1, f"expected exactly one tool_calls chunk, got {[c.type for c in chunks]}"
        calls = tool_call_chunks[0].tool_calls or []
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "new_answer"
        assert calls[0]["function"]["arguments"].get("content") == "42 is the answer"

    @pytest.mark.asyncio
    async def test_no_workflow_tool_calls_chunk_when_no_workflow_tools_passed(self, backend):
        """If orchestrator doesn't request workflow tools, don't parse for them
        (avoids false-positive matches in arbitrary agent text)."""
        proc_mock = AsyncMock()

        async def _aiter_stdout():
            # This LOOKS like a workflow JSON but the orchestrator didn't request workflow tools.
            yield b'{"tool_name": "new_answer", "arguments": {"content": "spurious"}}\n'

        proc_mock.stdout = _aiter_stdout()
        proc_mock.wait = AsyncMock(return_value=0)
        proc_mock.returncode = 0

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc_mock)):
            chunks = []
            async for chunk in backend.stream_with_tools(
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
            ):
                chunks.append(chunk)

        tool_call_chunks = [c for c in chunks if c.type == "tool_calls"]
        assert tool_call_chunks == [], "must not parse workflow tool calls when no workflow tools are requested"


class TestDockerModeApiKeyAuth:
    """Docker mode requires API-key auth because agy's OAuth state isn't portable
    into a container. The backend writes a workspace-local settings.json that
    forces `selectedType: gemini-api-key`, and refuses to construct without a key."""

    def test_docker_mode_requires_api_key_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        with patch.object(AntigravityCLIBackend, "_find_agy_cli", return_value="/fake/agy"):
            with pytest.raises(RuntimeError, match="GEMINI_API_KEY|GOOGLE_API_KEY|API.key"):
                AntigravityCLIBackend(
                    cwd=str(tmp_path / "cwd"),
                    command_line_execution_mode="docker",
                )

    def test_docker_mode_writes_api_key_settings_json(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "dummy-test-key")
        with patch.object(AntigravityCLIBackend, "_find_agy_cli", return_value="/fake/agy"):
            be = AntigravityCLIBackend(
                cwd=str(tmp_path / "cwd"),
                command_line_execution_mode="docker",
            )
            be._write_workspace_settings_json()
            settings_path = be._workspace_config_dir() / "settings.json"
            assert settings_path.exists()
            settings = json.loads(settings_path.read_text())
            assert settings.get("security", {}).get("auth", {}).get("selectedType") == "gemini-api-key"

    def test_local_mode_does_not_require_api_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        # Local mode uses OAuth from the host's ~/.gemini/google_accounts.json.
        with patch.object(AntigravityCLIBackend, "_find_agy_cli", return_value="/fake/agy"):
            AntigravityCLIBackend(cwd=str(tmp_path / "cwd"))  # must not raise


class TestNativeHookAdapter:
    """agy 1.0.0 inherits Gemini CLI's hook framework (same exa.hooks_pb proto,
    same BeforeTool/AfterTool/Stop events). The backend exposes a thin
    AntigravityCLINativeHookAdapter so orchestrator code can register hooks
    just as it does for GeminiCLIBackend."""

    def test_backend_exposes_native_hook_adapter(self, backend):
        adapter = backend.get_native_hook_adapter()
        assert adapter is not None
        from massgen.mcp_tools.native_hook_adapters.antigravity_cli_adapter import (
            AntigravityCLINativeHookAdapter,
        )

        assert isinstance(adapter, AntigravityCLINativeHookAdapter)

    def test_adapter_inherits_gemini_cli_hook_behavior(self):
        from massgen.mcp_tools.native_hook_adapters.antigravity_cli_adapter import (
            AntigravityCLINativeHookAdapter,
        )
        from massgen.mcp_tools.native_hook_adapters.gemini_cli_adapter import (
            GeminiCLINativeHookAdapter,
        )

        assert issubclass(AntigravityCLINativeHookAdapter, GeminiCLINativeHookAdapter)


class TestSubprocessEnv:
    """Env passed to agy must include API keys (passthrough) and disable auto-update during tests."""

    def test_build_subprocess_env_passes_through_gemini_api_key(self, monkeypatch, backend):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key-abc")
        env = backend._build_subprocess_env()
        assert env.get("GEMINI_API_KEY") == "test-key-abc"

    def test_build_subprocess_env_disables_auto_update_when_requested(self, backend):
        backend.disable_auto_update = True
        env = backend._build_subprocess_env()
        assert env.get("AGY_CLI_DISABLE_AUTO_UPDATE") == "1"
