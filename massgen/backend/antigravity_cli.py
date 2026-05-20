"""Antigravity CLI Backend - subprocess wrapper for Google's `agy` CLI.

The Antigravity CLI (a.k.a. `agy`, released at Google I/O 2026) is the
successor to Gemini CLI for consumer tiers as of 2026-06-18. It is a Go
binary installed by `https://antigravity.google/cli/install.sh` to
``~/.local/bin/agy`` and self-updates from there.

Compared to GeminiCLIBackend this wrapper is intentionally minimal:

- No ``--output-format stream-json``: agy emits plain text on stdout. We
  tail the per-session ``transcript.jsonl`` written by agy under
  ``<cwd>/.antigravity/antigravity-cli/brain/<uuid>/.system_generated/logs/``
  concurrently with the subprocess to get real-time thinking + tool events,
  and forward stdout lines as content chunks on process exit.
- No ``--model``: the model is selected server-side per the user's
  Antigravity tier (Gemini 3.5 Flash by default). A ``model`` config value
  is accepted for logging/registry consistency but ignored at invocation.
- ``--conversation <id>`` replaces ``--resume <id>``.
- ``--dangerously-skip-permissions`` replaces ``--approval-mode yolo``.
- Per-project isolation via the hidden ``--gemini_dir <abs_path>`` flag (not
  shown in ``--help`` but exposed by the binary's flag table and verified
  live). Each session writes MCP config + settings to ``<cwd>/.antigravity/``
  and never mutates the user's ``~/.gemini/``.
- MCP server entries use ``serverUrl`` (not ``url``) for HTTP servers per
  agy's ``mcp_config.json`` schema.

Authentication: agy honors the existing Google OAuth login at
``~/.gemini/google_accounts.json``. ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY``
are passed through to the subprocess env so future API-key auth (if added
by Google) works transparently.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from ..logger_config import logger
from ._streaming_buffer_mixin import StreamingBufferMixin
from .base import FilesystemSupport, LLMBackend, StreamChunk
from .native_tool_mixin import NativeToolBackendMixin

AGY_DEFAULT_MODEL_LABEL = "Gemini 3.5 Flash (High)"
AGY_AGENT_ID_LITERAL = "antigravity_cli"
AGY_MCP_CONFIG_PATH = Path.home() / ".gemini" / "config" / "mcp_config.json"


class AntigravityCLIBackend(NativeToolBackendMixin, StreamingBufferMixin, LLMBackend):
    """Antigravity CLI backend wrapping the `agy` Go binary.

    Inherits ``NativeToolBackendMixin`` for native-hook adapter wiring and
    ``StreamingBufferMixin`` for context-compression recovery. Hooks use the
    ``AntigravityCLINativeHookAdapter`` (a thin subclass of the Gemini CLI
    adapter — same exa.hooks_pb schema, same settings.json shape).
    """

    def __init__(self, api_key: str | None = None, **kwargs):
        super().__init__(api_key, **kwargs)
        self.__init_native_tool_mixin__()
        self._init_native_hook_adapter(
            "massgen.mcp_tools.native_hook_adapters.antigravity_cli_adapter.AntigravityCLINativeHookAdapter",
        )

        configured_env = self._get_configured_credentials_env() if hasattr(self, "_get_configured_credentials_env") else {}
        self.api_key = (
            api_key
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or (configured_env.get("GEMINI_API_KEY") if configured_env else None)
            or (configured_env.get("GOOGLE_API_KEY") if configured_env else None)
        )

        # agy supports OAuth-only auth via ~/.gemini/google_accounts.json; an
        # API key is *also* honored (passed through) but not required.
        self.use_login = not bool(self.api_key)

        self.dangerously_skip_permissions: bool = kwargs.get(
            "dangerously_skip_permissions",
            kwargs.get("approval_mode", "yolo") == "yolo",
        )
        self.disable_auto_update: bool = kwargs.get("disable_auto_update", True)

        # Accept a `model` for logging/registry consistency but warn that agy
        # ignores it at invocation time.
        self.model = kwargs.get("model", AGY_DEFAULT_MODEL_LABEL)
        if kwargs.get("model") and not self.model.lower().startswith("gemini"):
            logger.warning(
                f"Antigravity CLI: configured model '{self.model}' is not a known " "Gemini label. agy selects models server-side; this value is " "informational only.",
            )

        self._config_cwd = kwargs.get("cwd")
        self.system_prompt = kwargs.get("system_prompt", "")
        self.agent_id = kwargs.get("agent_id")

        configured_mcp_servers = kwargs.get("mcp_servers", [])
        self.mcp_servers: list[dict[str, Any]] = list(configured_mcp_servers) if isinstance(configured_mcp_servers, list) else []

        # Workspace-local MCP config (managed via --gemini_dir).
        self._mcp_config_managed_names: set[str] = set()

        # Docker mode: agy's OAuth token state lives in HOME-scoped storage that
        # doesn't cross container boundaries. Require an API key instead.
        self._docker_execution = kwargs.get("command_line_execution_mode") == "docker"
        if self._docker_execution and not self.api_key:
            raise RuntimeError(
                "Antigravity CLI Docker mode requires GEMINI_API_KEY or "
                "GOOGLE_API_KEY in the environment (OAuth state doesn't cross "
                "container boundaries). Set the API key in your shell or your "
                "agent config, then re-run.",
            )

        self._agy_path = self._find_agy_cli()
        if not self._agy_path:
            raise RuntimeError(
                "Antigravity CLI ('agy') not found. Install with:\n"
                "  curl -fsSL https://antigravity.google/cli/install.sh | bash\n"
                "Default install path is ~/.local/bin/agy. "
                "Run `agy --version` to verify.",
            )

    @property
    def cwd(self) -> str:
        if self.filesystem_manager:
            return str(Path(str(self.filesystem_manager.get_current_workspace())).resolve())
        return self._config_cwd or os.getcwd()

    # ── Binary discovery ──────────────────────────────────────────────────

    @staticmethod
    def _find_agy_cli() -> str | None:
        """Locate the agy binary. Returns absolute path or None."""
        on_path = shutil.which("agy")
        if on_path:
            return on_path
        candidates = [
            Path.home() / ".local" / "bin" / "agy",
            Path("/usr/local/bin/agy"),
            Path("/opt/homebrew/bin/agy"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return None

    # ── MCP config ────────────────────────────────────────────────────────

    def _build_mcp_config_dict(self) -> dict[str, Any]:
        """Translate MassGen MCP server entries to agy's mcp_config.json schema.

        agy uses ``serverUrl`` for HTTP servers (not ``url``) and
        ``command``/``args``/``env`` for stdio. SDK-only entries are excluded.
        """
        merged: dict[str, Any] = {}
        config_mcp = self.config.get("mcp_servers") if self.config else None

        servers: list[dict[str, Any]] = []
        if isinstance(config_mcp, dict):
            for name, srv in config_mcp.items():
                if isinstance(srv, dict) and srv.get("type") != "sdk":
                    srv = dict(srv)
                    srv["name"] = name
                    servers.append(srv)
        elif isinstance(config_mcp, list):
            servers.extend(s for s in config_mcp if isinstance(s, dict))

        existing_names = {s.get("name") for s in servers if s.get("name")}
        for s in self.mcp_servers:
            if isinstance(s, dict) and s.get("name") and s.get("name") not in existing_names:
                servers.append(s)
                existing_names.add(s.get("name"))

        for srv in servers:
            name = srv.get("name")
            if not name or srv.get("type") == "sdk":
                continue
            entry: dict[str, Any] = {}
            if srv.get("command"):
                entry["command"] = srv["command"]
            if srv.get("args"):
                entry["args"] = list(srv["args"])
            if srv.get("env"):
                entry["env"] = dict(srv["env"])
            # HTTP servers: agy expects `serverUrl`, not `url`. Accept either
            # in the source config and emit the canonical key.
            http_url = srv.get("serverUrl") or srv.get("url") or srv.get("httpUrl")
            if http_url:
                entry["serverUrl"] = http_url
                if srv.get("headers"):
                    entry["headers"] = dict(srv["headers"])
            if entry:
                merged[name] = entry

        return merged

    def _workspace_config_dir(self) -> Path:
        """Project-scoped agy data root, passed via ``--gemini_dir``."""
        return Path(self.cwd).resolve() / ".antigravity"

    def _workspace_mcp_config_path(self) -> Path:
        """Where to drop our merged mcp_config.json so agy reads it."""
        return self._workspace_config_dir() / "config" / "mcp_config.json"

    def _write_mcp_config(self) -> None:
        """Write MassGen MCP servers into the workspace-local mcp_config.json.

        Because we pass ``--gemini_dir <workspace>`` to agy, this is the file
        agy reads — the user's global ``~/.gemini/config/mcp_config.json`` is
        never touched. Cleanup just removes the workspace file.
        """
        new_servers = self._build_mcp_config_dict()
        if not new_servers:
            return

        path = self._workspace_mcp_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"mcpServers": new_servers}, indent=2), encoding="utf-8")
        self._mcp_config_managed_names = set(new_servers.keys())
        logger.info(
            f"Antigravity CLI: wrote {len(new_servers)} MCP server(s) to {path} " f"(servers: {sorted(self._mcp_config_managed_names)})",
        )

    def _restore_mcp_config(self) -> None:
        """Remove the workspace-local mcp_config.json written by this backend."""
        path = self._workspace_mcp_config_path()
        if path.exists():
            try:
                path.unlink()
                logger.info(f"Antigravity CLI: removed workspace {path}")
            except OSError as exc:
                logger.warning(f"Antigravity CLI: failed to remove {path}: {exc}")
        self._mcp_config_managed_names = set()

    def _workspace_agents_md_path(self) -> Path:
        """Path to AGENTS.md in the agent workspace.

        agy loads ``AGENTS.md``/``GEMINI.md`` from the workspace root as
        persistent context. We use this as the system-prompt channel since
        ``agy -p`` has no separate system message input.
        """
        return Path(self.cwd).resolve() / "AGENTS.md"

    def _workspace_agents_md_backup_path(self) -> Path:
        return Path(self.cwd).resolve() / ".AGENTS.md.massgen_backup"

    def _write_system_prompt_md(self) -> None:
        """Write the MassGen system prompt to <cwd>/AGENTS.md.

        agy treats AGENTS.md as persistent workspace context (not as the user
        request), so the model sees coordination/workflow instructions in the
        right channel instead of inside ``<USER_REQUEST>``. Backs up any
        pre-existing AGENTS.md so :meth:`_restore_system_prompt_md` can put
        the original back.
        """
        if not self.system_prompt:
            return
        path = self._workspace_agents_md_path()
        backup = self._workspace_agents_md_backup_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not backup.exists():
            try:
                path.replace(backup)
                logger.info(f"Antigravity CLI: backed up existing {path} -> {backup}")
            except OSError as exc:
                logger.warning(f"Antigravity CLI: could not back up {path}: {exc}")
        path.write_text(self.system_prompt, encoding="utf-8")
        logger.info(
            f"Antigravity CLI: wrote system prompt ({len(self.system_prompt)} chars) to {path}",
        )

    def _restore_system_prompt_md(self) -> None:
        """Restore the user's original AGENTS.md, or remove ours if none existed."""
        path = self._workspace_agents_md_path()
        backup = self._workspace_agents_md_backup_path()
        try:
            if backup.exists():
                backup.replace(path)
                logger.info(f"Antigravity CLI: restored original AGENTS.md from {backup}")
            elif path.exists():
                path.unlink()
                logger.info(f"Antigravity CLI: removed managed {path}")
        except OSError as exc:
            logger.warning(f"Antigravity CLI: failed to clean up AGENTS.md: {exc}")

    def _write_workspace_settings_json(self) -> None:
        """Write a minimal settings.json in the workspace config dir.

        In Docker mode (or any time we have an API key but no host OAuth
        login), this forces agy to use `selectedType: "gemini-api-key"` so it
        won't try to start the OAuth flow inside a headless container. The key
        itself is provided via the ``GEMINI_API_KEY`` env var, not in this file.
        """
        config_dir = self._workspace_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_path = config_dir / "settings.json"
        settings: dict[str, Any] = {}
        if settings_path.exists():
            try:
                raw = settings_path.read_text(encoding="utf-8").strip()
                if raw:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        settings = parsed
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    f"Antigravity CLI: could not parse existing {settings_path} " f"({exc}); overwriting.",
                )
        if self._docker_execution or self.api_key:
            settings.setdefault("security", {}).setdefault("auth", {})["selectedType"] = "gemini-api-key"
        settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    # ── Command construction ──────────────────────────────────────────────

    def _agy_log_file_path(self) -> Path:
        """Per-call log file path agy writes via ``--log-file``.

        agy treats backend errors (quota 429, auth failures, etc.) as
        non-fatal — it exits with code 0 and an empty stdout. We capture the
        log so we can surface the real reason instead of an empty retry loop.
        """
        return self._workspace_config_dir() / "antigravity-cli" / "agy.log"

    def _build_exec_command(self, prompt: str) -> list[str]:
        """Build the agy subprocess command for non-interactive print mode.

        Always passes ``--gemini_dir <abs_path>`` so agy reads our workspace-local
        config (mcp_config.json, settings.json) instead of the user's global one.

        Each MassGen call is a single-shot ``-p`` invocation — the orchestrator
        already injects prior-response context into retry prompts, so agy's
        ``--continue``/``--conversation`` session resumption is unnecessary (and
        ``--conversation`` with a UUID we generated fails with
        "conversation X not found" since agy assigns its own IDs).
        """
        cmd: list[str] = [self._agy_path]
        cmd.extend(["--gemini_dir", str(self._workspace_config_dir())])
        log_path = self._agy_log_file_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--log-file", str(log_path)])
        if self.dangerously_skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        cmd.extend(["-p", prompt])
        return cmd

    def _scan_agy_log_for_errors(self) -> str | None:
        """Return a user-facing error string if agy's log shows a known failure.

        agy logs failures (quota 429, auth, etc.) at level ``E`` but still
        exits 0 with empty stdout, which leaves MassGen looping on empty
        retries. Surfacing the real message lets the orchestrator (and the
        user) see what actually happened.
        """
        log_path = self._agy_log_file_path()
        if not log_path.exists():
            return None
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        if "RESOURCE_EXHAUSTED" in text or "code 429" in text:
            for line in text.splitlines():
                if "RESOURCE_EXHAUSTED" in line or "code 429" in line:
                    return f"Antigravity quota exhausted: {line.strip()}"
            return "Antigravity quota exhausted (HTTP 429)."
        if "PERMISSION_DENIED" in text or "UNAUTHENTICATED" in text:
            return "Antigravity authentication failed — run `agy` interactively to log in, or set GEMINI_API_KEY."
        return None

    def _build_subprocess_env(self) -> dict[str, str]:
        """Build the env passed to agy. Includes API-key passthrough and
        opt-in auto-update suppression (useful for deterministic tests).

        Live env vars take precedence so callers (and tests) can override
        the api_key captured at backend construction.
        """
        env = dict(os.environ)
        env["NO_COLOR"] = "1"
        if self.api_key:
            env.setdefault("GEMINI_API_KEY", self.api_key)
            env.setdefault("GOOGLE_API_KEY", self.api_key)
        if self.disable_auto_update:
            env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "1"
        return env

    # ── Transcript tailing ────────────────────────────────────────────────

    @staticmethod
    def _existing_transcripts(brain_dir: Path) -> set[Path]:
        if not brain_dir.exists():
            return set()
        return set(brain_dir.rglob("transcript.jsonl"))

    async def _find_and_tail_transcript(
        self,
        brain_dir: Path,
        pre_existing: set[Path],
        proc: asyncio.subprocess.Process,
    ) -> AsyncGenerator[StreamChunk]:
        """Locate the new transcript.jsonl agy creates and tail it in real-time."""
        transcript_path: Path | None = None
        for _ in range(100):  # up to 10 s before giving up
            if brain_dir.exists():
                for p in brain_dir.rglob("transcript.jsonl"):
                    if p not in pre_existing:
                        transcript_path = p
                        break
            if transcript_path:
                break
            if proc.returncode is not None:
                break
            await asyncio.sleep(0.1)

        if not transcript_path:
            return

        seen: set[int] = set()
        # FIFO queue of pending tool calls emitted from PLANNER_RESPONSE, matched
        # in order against subsequent RUN_COMMAND / CODE_ACTION result events.
        pending_tool_calls: list[dict[str, Any]] = []

        def process(event: dict[str, Any]) -> None:
            step = event.get("step_index", -1)
            if step in seen:
                return
            seen.add(step)
            self._process_transcript_event(event, pending_tool_calls)

        with open(transcript_path) as fh:
            while True:
                line = fh.readline()
                if line:
                    line = line.strip()
                    if line:
                        try:
                            process(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                else:
                    if proc.returncode is not None:
                        for line in fh:
                            line = line.strip()
                            if line:
                                try:
                                    process(json.loads(line))
                                except json.JSONDecodeError:
                                    pass
                        break
                    await asyncio.sleep(0.1)

        # Async generator must yield at least once — nothing to yield since all
        # output goes directly through the event emitter.
        return
        yield  # make this function an async generator

    def _process_transcript_event(
        self,
        event: dict[str, Any],
        pending_tool_calls: list[dict[str, Any]],
    ) -> None:
        """Emit structured TUI events for a single transcript entry.

        Uses the event emitter directly so the Textual TUI renders proper
        thinking bubbles and tool cards, not just mcp_status text blobs.
        """
        from massgen.logger_config import get_event_emitter

        source = event.get("source", "")
        event_type = event.get("type", "")
        status = event.get("status", "")
        _emitter = get_event_emitter()

        if source == "MODEL" and event_type == "PLANNER_RESPONSE":
            thinking = event.get("thinking", "")
            if thinking and _emitter:
                _emitter.emit_thinking(thinking, agent_id=self.agent_id)

            for tc in event.get("tool_calls", []):
                args = tc.get("args", {})
                action = args.get("toolAction") or args.get("toolSummary") or tc.get("name", "tool")
                if isinstance(action, str):
                    action = action.strip('"')
                tool_name = tc.get("name", "run_command")
                tool_id = f"agy_{event.get('step_index', 0)}_{len(pending_tool_calls)}"

                pending_tool_calls.append(
                    {
                        "tool_id": tool_id,
                        "tool_name": tool_name,
                        "action": action,
                        "created_at": event.get("created_at", ""),
                    },
                )

                if _emitter:
                    _emitter.emit_tool_start(
                        tool_id=tool_id,
                        tool_name=f"agy_{tool_name}",
                        args={"action": action},
                        server_name="agy",
                        agent_id=self.agent_id,
                    )

        elif source == "MODEL" and event_type in ("RUN_COMMAND", "CODE_ACTION"):
            pending = pending_tool_calls.pop(0) if pending_tool_calls else None
            if not pending or not _emitter:
                return

            is_error = status == "ERROR"
            content = event.get("content", "")
            if status == "DONE" and content:
                result = content.split("Output:\n", 1)[-1].strip() if "Output:\n" in content else ""
                if not result and "Created file" in content:
                    result = content.split("\n")[0].strip()
            elif is_error:
                result = content[:300]
            else:
                result = ""

            elapsed = 0.0
            try:
                from datetime import datetime, timezone

                fmt = "%Y-%m-%dT%H:%M:%SZ"
                t0 = datetime.strptime(pending["created_at"], fmt).replace(tzinfo=timezone.utc)
                t1 = datetime.strptime(event.get("created_at", pending["created_at"]), fmt).replace(tzinfo=timezone.utc)
                elapsed = (t1 - t0).total_seconds()
            except Exception:
                pass

            _emitter.emit_tool_complete(
                tool_id=pending["tool_id"],
                tool_name=f"agy_{pending['tool_name']}",
                result=result[:500] if result else "(no output)",
                elapsed_seconds=elapsed,
                status="error" if is_error else "success",
                is_error=is_error,
                agent_id=self.agent_id,
            )

    # ── Streaming ─────────────────────────────────────────────────────────

    async def _stream_local(
        self,
        prompt: str,
    ) -> AsyncGenerator[StreamChunk]:
        """Run agy as a subprocess, tailing transcript.jsonl for real-time events."""
        cmd = self._build_exec_command(prompt)
        env = self._build_subprocess_env()
        logger.info("Running Antigravity CLI")

        brain_dir = self._workspace_config_dir() / "antigravity-cli" / "brain"
        pre_existing = self._existing_transcripts(brain_dir)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=self.cwd,
            env=env,
        )

        try:
            self.record_first_token()
        except (AttributeError, TypeError):
            pass
        yield StreamChunk(type="content", content="[Antigravity CLI] Running...\n")

        # Use a queue to merge stdout reader + transcript tailer.
        _DONE: object = object()
        queue: asyncio.Queue[StreamChunk | object] = asyncio.Queue()

        produced_real_output = {"value": False}

        async def _read_stdout() -> None:
            try:
                async for raw_line in proc.stdout:
                    text = raw_line.decode("utf-8", errors="replace")
                    if text:
                        produced_real_output["value"] = True
                        await queue.put(StreamChunk(type="content", content=text))
            finally:
                await proc.wait()
                await queue.put(_DONE)

        async def _tail() -> None:
            try:
                async for chunk in self._find_and_tail_transcript(brain_dir, pre_existing, proc):
                    produced_real_output["value"] = True
                    await queue.put(chunk)
            finally:
                await queue.put(_DONE)

        asyncio.create_task(_read_stdout())
        asyncio.create_task(_tail())

        done_count = 0
        try:
            while done_count < 2:
                item = await queue.get()
                if item is _DONE:
                    done_count += 1
                else:
                    yield item  # type: ignore[misc]
        except Exception as exc:
            logger.error(f"Antigravity CLI streaming error: {exc}")
            yield StreamChunk(type="error", error=str(exc))
            return

        rc = proc.returncode
        if rc != 0:
            err_msg = f"agy exited with code {rc}"
            yield StreamChunk(type="error", error=err_msg)
            try:
                self.end_api_call_timing(success=False, error=err_msg)
            except (AttributeError, TypeError):
                pass
            return

        # agy exits 0 with empty stdout on quota/auth failures — surface what
        # the log file actually says so the orchestrator doesn't retry-loop
        # against an empty response.
        if not produced_real_output["value"]:
            err_msg = self._scan_agy_log_for_errors() or ("agy returned no output (process exited cleanly with empty stdout " "and no transcript activity). Check agy's log file for details.")
            logger.error(f"Antigravity CLI: silent failure — {err_msg}")
            yield StreamChunk(type="content", content=f"\n[Antigravity CLI ERROR] {err_msg}\n")
            yield StreamChunk(type="error", error=err_msg)
            try:
                self.end_api_call_timing(success=False, error=err_msg)
            except (AttributeError, TypeError):
                pass
            return

        yield StreamChunk(type="done", usage={})
        try:
            self.end_api_call_timing(success=True)
        except (AttributeError, TypeError):
            pass

    async def stream_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        **kwargs,
    ) -> AsyncGenerator[StreamChunk]:
        """Stream a response from agy. Workflow tools (vote/new_answer) are
        injected as text instructions into the prompt and parsed from stdout,
        because agy 1.0.0's print-mode CLI does not load MCP tools mid-session.
        """
        from ..tool.workflow_toolkits.base import WORKFLOW_TOOL_NAMES
        from .base import build_workflow_instructions, parse_workflow_tool_calls

        prompt = self._build_prompt_from_messages(messages)
        if not prompt.strip():
            yield StreamChunk(type="error", error="No user message found in messages")
            return

        latest_system = self._extract_latest_system_message(messages)
        if latest_system:
            self.system_prompt = latest_system

        # Workflow tools via text fallback: detect them in the tools arg, inject
        # formatting guidance into the prompt, and parse stdout for matching calls.
        workflow_tools_present = any((t.get("function", {}).get("name") or t.get("name")) in WORKFLOW_TOOL_NAMES for t in (tools or []))
        workflow_instructions = build_workflow_instructions(tools or []) if workflow_tools_present else ""
        workflow_allowed_names = {(t.get("function", {}).get("name") or t.get("name")) for t in (tools or []) if (t.get("function", {}).get("name") or t.get("name")) in WORKFLOW_TOOL_NAMES}

        # agy -p has no separate system channel — anything prepended to the
        # prompt ends up inside <USER_REQUEST>, which confused the model. The
        # MassGen system prompt is written to AGENTS.md instead (loaded by agy
        # as workspace context); the -p argument carries only workflow tool
        # guidance and the actual user message.
        prompt_parts: list[str] = []
        if workflow_instructions:
            prompt_parts.append(workflow_instructions)
        prompt_parts.append(prompt)
        full_prompt = "\n\n".join(p for p in prompt_parts if p)

        self._write_mcp_config()
        self._write_workspace_settings_json()
        self._write_system_prompt_md()
        try:
            try:
                self.start_api_call_timing(self.model)
            except (AttributeError, TypeError):
                pass

            self._clear_streaming_buffer(**kwargs) if hasattr(self, "_clear_streaming_buffer") else None

            accumulated_content = ""
            done_chunk: StreamChunk | None = None
            async for chunk in self._stream_local(full_prompt):
                if chunk.type == "content" and chunk.content:
                    accumulated_content += chunk.content
                    if hasattr(self, "_append_to_streaming_buffer"):
                        self._append_to_streaming_buffer(chunk.content)
                # Hold the `done` chunk so workflow tool_calls can be yielded
                # before terminal events (mirrors gemini_cli.py:1529-1531 pattern).
                if chunk.type == "done" and workflow_tools_present:
                    done_chunk = chunk
                    continue
                yield chunk

            if workflow_tools_present and accumulated_content:
                tool_calls = parse_workflow_tool_calls(
                    accumulated_content,
                    allowed_tool_names=workflow_allowed_names or None,
                )
                if tool_calls:
                    logger.info(
                        f"Antigravity CLI: parsed {len(tool_calls)} workflow tool call(s) " f"from agy stdout (text fallback path)",
                    )
                    yield StreamChunk(
                        type="tool_calls",
                        tool_calls=tool_calls,
                        source="antigravity_cli",
                    )

            if done_chunk is not None:
                yield done_chunk

            agent_id = self.agent_id or kwargs.get("agent_id")
            if hasattr(self, "_finalize_streaming_buffer"):
                self._finalize_streaming_buffer(agent_id=agent_id)
        finally:
            self._restore_mcp_config()
            self._restore_system_prompt_md()

    # ── Message helpers ───────────────────────────────────────────────────

    @staticmethod
    def _message_content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(c.get("text", "") for c in content if isinstance(c, dict) and isinstance(c.get("text"), str))
        return str(content)

    def _build_prompt_from_messages(self, messages: list[dict[str, Any]]) -> str:
        """Squash the user's latest message into a single prompt string."""
        for msg in reversed(messages or []):
            if msg.get("role") == "user":
                return self._message_content_to_text(msg.get("content", ""))
        return ""

    def _extract_latest_system_message(self, messages: list[dict[str, Any]]) -> str:
        latest = ""
        for msg in messages or []:
            if msg.get("role") == "system":
                latest = self._message_content_to_text(msg.get("content", ""))
        return latest

    # ── Provider metadata ─────────────────────────────────────────────────

    def get_provider_name(self) -> str:
        return "Antigravity CLI"

    def get_filesystem_support(self) -> FilesystemSupport:
        return FilesystemSupport.NATIVE

    def get_disallowed_tools(self, config: dict[str, Any]) -> list[str]:
        # agy has native filesystem + planning; suppress duplicate MassGen
        # custom tools that would conflict with built-ins.
        return [
            "enter_plan_mode",
            "exit_plan_mode",
            "save_memory",
            "ask_user",
            "write_todos",
        ]

    def get_tool_category_overrides(self) -> dict[str, str]:
        return {
            "filesystem": "skip",
            "command_execution": "skip",
            "file_search": "skip",
            "web_search": "skip",
            "planning": "override",
            "subagents": "override",
        }
