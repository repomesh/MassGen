"""
Shared utilities for checkpoint and gated_action sub-runs.

This module provides common functionality for spawning MassGen sub-runs
that are used by both the checkpoint and gated_action MCP tools.

Environment variables (read per sub-run at spawn time):

    MASSGEN_CHECKPOINT_WEB_UI  = "auto" | "view" | unset
        "auto" — enable the MassGen web UI for the sub-run AND open the
                 default browser to the session URL.
        "view" — enable the web UI and print the URL, but do NOT open a
                 browser. Useful when you want to inspect on demand.
        unset / anything else — no web UI (current default).

    MASSGEN_CHECKPOINT_WEB_PORT = integer
        Port to bind the web UI to. Default 8000. Override this when
        running multiple concurrent sub-runs to avoid collisions.

    MASSGEN_CHECKPOINT_WEB_HOST = string
        Host to bind the web UI to. Default 127.0.0.1 (localhost only).

Caveats:
- Port 8000 collides if multiple checkpoints run at once. Set a custom
  port via MASSGEN_CHECKPOINT_WEB_PORT per shell if needed.
- The MCP server and your browser must share a host (localhost binding
  is the default).
"""

import asyncio
import logging
import os
import shutil
import time
import webbrowser
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _web_ui_settings() -> tuple[str, str, int]:
    """Read web UI env vars. Returns (mode, host, port).

    mode is one of: "auto", "view", "none".
    """
    mode = os.environ.get("MASSGEN_CHECKPOINT_WEB_UI", "").strip().lower()
    if mode not in {"auto", "view"}:
        mode = "none"
    host = os.environ.get("MASSGEN_CHECKPOINT_WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port_raw = os.environ.get("MASSGEN_CHECKPOINT_WEB_PORT", "8000").strip() or "8000"
    try:
        port = int(port_raw)
    except ValueError:
        logger.warning(
            "[SubrunRunner] Invalid MASSGEN_CHECKPOINT_WEB_PORT=%r, falling back to 8000",
            port_raw,
        )
        port = 8000
    return mode, host, port


async def _open_browser_after_delay(url: str, delay_seconds: float = 2.0) -> None:
    """Open the default browser to `url` after a short delay.

    The delay gives the MassGen web server time to bind the port before
    the browser tries to load the page. Any failure is logged, not raised.
    """
    try:
        await asyncio.sleep(delay_seconds)
        webbrowser.open(url)
        logger.info("[SubrunRunner] Opened browser at %s", url)
    except Exception as e:  # pragma: no cover - best-effort
        logger.warning("[SubrunRunner] Could not open browser at %s: %s", url, e)


def deep_copy_dict(d: Any) -> Any:
    """Deep copy a dict/list structure without importing copy module."""
    if isinstance(d, dict):
        return {k: deep_copy_dict(v) for k, v in d.items()}
    elif isinstance(d, list):
        return [deep_copy_dict(item) for item in d]
    else:
        return d


def generate_subrun_config(
    parent_config: dict[str, Any],
    workspace: Path,
    exclude_mcp_servers: list[str] | None = None,
) -> dict[str, Any]:
    """
    Generate a YAML config for a sub-run.

    The sub-run config:
    - Inherits all agents from parent
    - Removes main_agent flag (all agents participate equally)
    - Optionally removes specified MCP servers (prevent recursion)
    - Sets workspace paths for the sub-run

    Args:
        parent_config: The parent orchestrator's config
        workspace: Path to the sub-run workspace
        exclude_mcp_servers: List of MCP server names to exclude (e.g., ["checkpoint", "gated_action"])

    Returns:
        Config dict ready to be written as YAML
    """
    exclude_mcp_servers = exclude_mcp_servers or ["checkpoint", "gated_action"]
    config = {}

    # Process agents section
    if "agents" in parent_config:
        config["agents"] = []
        for agent in parent_config["agents"]:
            agent_copy = deep_copy_dict(agent)
            # Remove main_agent flag - all agents participate equally in sub-run
            if "main_agent" in agent_copy:
                del agent_copy["main_agent"]
            # Filter out excluded MCP servers
            if "backend" in agent_copy and "mcp_servers" in agent_copy["backend"]:
                agent_copy["backend"]["mcp_servers"] = [s for s in agent_copy["backend"]["mcp_servers"] if s.get("name") not in exclude_mcp_servers]
            config["agents"].append(agent_copy)
    elif "agent" in parent_config:
        agent_copy = deep_copy_dict(parent_config["agent"])
        if "main_agent" in agent_copy:
            del agent_copy["main_agent"]
        if "backend" in agent_copy and "mcp_servers" in agent_copy["backend"]:
            agent_copy["backend"]["mcp_servers"] = [s for s in agent_copy["backend"]["mcp_servers"] if s.get("name") not in exclude_mcp_servers]
        config["agent"] = agent_copy

    # Copy orchestrator section with modifications
    if "orchestrator" in parent_config:
        config["orchestrator"] = deep_copy_dict(parent_config["orchestrator"])
    else:
        config["orchestrator"] = {}

    # Set workspace paths for sub-run
    config["orchestrator"]["snapshot_storage"] = str(workspace / "snapshots")
    config["orchestrator"]["agent_temporary_workspace"] = str(workspace / "temp")

    # Disable nested checkpoints/gated_actions at top level
    if "checkpoint" in config:
        del config["checkpoint"]
    if "gated_actions" in config:
        del config["gated_actions"]

    return config


def generate_checkpoint_config(
    parent_config: dict[str, Any],
    workspace: Path,
    signal: dict[str, Any],
) -> dict[str, Any]:
    """Generate a YAML config for a checkpoint sub-run.

    Extends ``generate_subrun_config`` with checkpoint-specific overrides:
    - Injects ``eval_criteria`` from the signal as inline checklist criteria
    - Injects ``personas`` from the signal into per-agent configs
    - Sets ``checkpoint_enabled: false`` to prevent recursion
    - Removes ``main_agent`` flags (all agents participate equally)

    Args:
        parent_config: The parent orchestrator's raw YAML config dict.
        workspace: Path to the checkpoint sub-run workspace.
        signal: The checkpoint signal dict (task, eval_criteria, personas, etc.).

    Returns:
        Config dict ready to be written as YAML for the subprocess.
    """
    # Start with base subrun config (removes main_agent, filters MCPs)
    config = generate_subrun_config(
        parent_config,
        workspace,
        exclude_mcp_servers=["checkpoint", "gated_action", "massgen_checkpoint"],
    )

    # Ensure orchestrator.coordination section exists
    if "orchestrator" not in config:
        config["orchestrator"] = {}
    coord = config["orchestrator"].setdefault("coordination", {})

    # Disable checkpoint in the subprocess to prevent recursion
    coord["checkpoint_enabled"] = False

    # Inject eval_criteria as checklist-gated evaluation mode
    eval_criteria = signal.get("eval_criteria", [])
    if eval_criteria:
        coord["evaluation_mode"] = "checklist_gated"
        coord["inline_checklist_criteria"] = list(eval_criteria)

    # Inject personas into agent configs (handles both "agents" list and "agent" singular)
    personas = signal.get("personas") or {}
    if personas:
        agents_list = config.get("agents", [])
        if not agents_list and "agent" in config:
            agents_list = [config["agent"]]
        for agent_cfg in agents_list:
            agent_id = agent_cfg.get("id", "")
            if agent_id in personas:
                agent_cfg["persona"] = personas[agent_id]

    return config


def sync_workspace_from_subrun(
    subrun_workspace: Path,
    main_workspace: Path,
    skip_files: list[str] | None = None,
) -> list[dict[str, str]]:
    """
    Sync workspace changes from sub-run back to main workspace.

    Args:
        subrun_workspace: Path to the sub-run's workspace
        main_workspace: Path to the main agent's workspace
        skip_files: List of filenames to skip (e.g., ["answer.txt", "status.json"])

    Returns:
        List of dicts with "file" and "change" (modified|created) keys
    """
    skip_files = skip_files or ["answer.txt", "status.json", "_registry.json"]
    changes = []

    # Find the actual work directories in sub-run workspace
    # Sub-runs may create agent workspaces under workspaces/ or temp/
    subrun_work_dirs = []

    # Check for workspaces directory (multi-agent)
    workspaces_dir = subrun_workspace / "workspaces"
    if workspaces_dir.exists():
        for agent_dir in workspaces_dir.iterdir():
            if agent_dir.is_dir():
                subrun_work_dirs.append(agent_dir)

    # Check for temp directory
    temp_dir = subrun_workspace / "temp"
    if temp_dir.exists():
        subrun_work_dirs.append(temp_dir)

    # If no specific work dirs found, use the workspace itself
    if not subrun_work_dirs:
        subrun_work_dirs = [subrun_workspace]

    # Sync files from sub-run to main
    for work_dir in subrun_work_dirs:
        for item in work_dir.rglob("*"):
            if item.is_file():
                # Skip hidden files/directories
                if any(part.startswith(".") for part in item.relative_to(work_dir).parts):
                    continue
                # Skip specified files
                if item.name in skip_files:
                    continue

                rel_path = item.relative_to(work_dir)
                dest_path = main_workspace / rel_path

                # Create parent directories
                dest_path.parent.mkdir(parents=True, exist_ok=True)

                # Check if file changed
                if dest_path.exists():
                    try:
                        with open(item, "rb") as f1, open(dest_path, "rb") as f2:
                            if f1.read() == f2.read():
                                continue  # No change
                    except OSError:
                        pass  # If we can't read, assume changed
                    change_type = "modified"
                else:
                    change_type = "created"

                # Copy the file
                try:
                    shutil.copy2(item, dest_path)
                    changes.append(
                        {
                            "file": str(rel_path),
                            "change": change_type,
                        },
                    )
                    logger.info(f"[SubrunSync] Synced {change_type} file: {rel_path}")
                except OSError as e:
                    logger.warning(f"[SubrunSync] Failed to sync {rel_path}: {e}")

    return changes


async def run_massgen_subrun(
    prompt: str,
    config_path: Path,
    workspace: Path,
    timeout: int,
    answer_file: Path | None = None,
) -> dict[str, Any]:
    """
    Spawn and run a MassGen sub-run.

    Args:
        prompt: The task prompt for the sub-run
        config_path: Path to the sub-run config YAML
        workspace: Working directory for the sub-run
        timeout: Maximum execution time in seconds
        answer_file: Optional path for answer output (defaults to workspace/answer.txt)

    Returns:
        Dict with success, output/error, and execution time
    """
    if answer_file is None:
        answer_file = workspace / "answer.txt"

    # Build command.
    #
    # --no-parse-at-references: checkpoint/subrun objectives are AI-generated
    # and routinely contain literal '@' characters (commit SHAs, emails, file
    # URLs, CSS @media, etc.) that must NOT be misinterpreted as @path context
    # references. Context paths for subruns are passed explicitly via config,
    # not through prompt parsing. Same rationale as SubagentOrchestratorConfig
    # defaulting parse_at_references=False.
    cmd = [
        "uv",
        "run",
        "massgen",
        "--config",
        str(config_path),
        "--automation",
        "--no-session-registry",
        "--no-parse-at-references",
        "--output-file",
        str(answer_file),
    ]

    # Optional web UI (env-driven — see module docstring).
    web_mode, web_host, web_port = _web_ui_settings()
    web_url: str | None = None
    if web_mode != "none":
        cmd.extend(
            [
                "--web",
                "--web-host",
                web_host,
                "--web-port",
                str(web_port),
                "--no-browser",  # we open the browser ourselves after a delay
            ],
        )
        # The bare URL is enough: when MassGen runs with --automation,
        # `/api/setup/status` reports needs_setup=false (server.py change)
        # so the frontend skips the first-run wizard entirely and lands
        # on the live coordination view. The frontend then calls
        # /api/active-session and auto-attaches to the run that
        # --automation kicked off.
        web_url = f"http://{web_host}:{web_port}/"
        logger.info(
            "[SubrunRunner] Web UI enabled (mode=%s) at %s",
            web_mode,
            web_url,
        )
        # Surface URL prominently to stderr so the user sees it even with
        # --automation suppressing most output.
        print(
            f"[massgen-checkpoint-mcp] Web UI: {web_url}  (mode={web_mode})",
            flush=True,
        )

    cmd.append(prompt)

    logger.info(f"[SubrunRunner] Spawning sub-run with config: {config_path}")

    start_time = time.time()

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workspace),
        )

        # In "auto" mode, open the browser shortly after the subprocess
        # starts. We schedule this as a background task so it doesn't
        # block the await on process.communicate() below.
        if web_mode == "auto" and web_url is not None:
            asyncio.create_task(_open_browser_after_delay(web_url))

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning(
                f"[SubrunRunner] Sub-run timed out after {timeout}s, terminating...",
            )
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except TimeoutError:
                process.kill()
                await process.wait()

            return {
                "success": False,
                "error": f"Sub-run timed out after {timeout} seconds",
                "execution_time_seconds": time.time() - start_time,
            }

        execution_time = time.time() - start_time

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            logger.error(f"[SubrunRunner] Sub-run failed: {error_msg}")
            return {
                "success": False,
                "error": f"Sub-run failed with code {process.returncode}: {error_msg}",
                "execution_time_seconds": execution_time,
            }

        # Read output from answer file
        output = ""
        if answer_file.exists():
            output = answer_file.read_text().strip()
        else:
            output = stdout.decode() if stdout else ""

        return {
            "success": True,
            "output": output,
            "execution_time_seconds": execution_time,
        }

    except Exception as e:
        logger.error(f"[SubrunRunner] Error running sub-run: {e}")
        return {
            "success": False,
            "error": str(e),
            "execution_time_seconds": time.time() - start_time,
        }


def build_checkpoint_mcp_config(
    workspace_path: Path,
    agent_id: str,
    gated_patterns: list[str] | None = None,
) -> dict[str, Any]:
    """
    Build an MCP server config for the checkpoint tool.

    Args:
        workspace_path: Path to the main agent's workspace.
        agent_id: The main agent's ID.
        gated_patterns: List of fnmatch patterns for tools requiring approval.

    Returns:
        MCP server config dict suitable for inclusion in backend.mcp_servers.
    """
    import json as _json

    args = [
        "--workspace-path",
        str(workspace_path),
        "--agent-id",
        agent_id,
    ]
    if gated_patterns:
        args.extend(["--gated-patterns", _json.dumps(gated_patterns)])

    return {
        "name": "massgen_checkpoint",
        "type": "stdio",
        "command": "python",
        "args": [
            "-m",
            "massgen.mcp_tools.checkpoint._checkpoint_mcp_server",
        ]
        + args,
    }


def build_standalone_checkpoint_mcp_config(
    team_config_path: str,
    mode: str | None = None,
    single_checkpoint: bool | None = None,
    include_workspace_context: bool | None = None,
    default_workspace_dir: str | None = None,
    default_trajectory_path: str | None = None,
) -> dict[str, Any]:
    """Build an MCP server config that exposes the standalone checkpoint tools.

    The standalone server (`massgen.mcp_tools.standalone.checkpoint_mcp_server`)
    reads a team YAML via `--config` and itself spawns sub-MassGen subprocesses
    to evaluate each checkpoint.

    Mode flags (`mode`, `single_checkpoint`, `include_workspace_context`) live
    in two places: the team YAML the server loads, AND the parent MassGen run's
    `coordination.standalone_checkpoint` block. To keep the two from drifting
    (which would let the agent's prompt promise an affordance the server
    doesn't actually grant), the parent passes its values as CLI args here and
    the server lets them override the YAML at startup.

    Args:
        team_config_path: Path to the team YAML the standalone server runs.
        mode: When set, override the team YAML's `mode` ("generate"/"verify").
        single_checkpoint: When set, override the team YAML's `single_checkpoint`.
        include_workspace_context: When set, override the team YAML's flag.

    Returns:
        MCP server config dict suitable for inclusion in backend.mcp_servers.
    """
    if not team_config_path:
        raise ValueError(
            "build_standalone_checkpoint_mcp_config requires a non-empty team_config_path",
        )
    args = [
        "-m",
        "massgen.mcp_tools.standalone.checkpoint_mcp_server",
        "--config",
        str(team_config_path),
    ]
    if mode is not None:
        args.extend(["--mode", str(mode)])
    if single_checkpoint:
        args.append("--single-checkpoint")
    if include_workspace_context:
        args.append("--include-workspace-context")
    if default_workspace_dir:
        args.extend(["--default-workspace-dir", str(default_workspace_dir)])
    if default_trajectory_path:
        args.extend(["--default-trajectory-path", str(default_trajectory_path)])
    return {
        "name": "massgen_checkpoint_standalone",
        "type": "stdio",
        "command": "python",
        "args": args,
    }


def write_subrun_config(
    config: dict[str, Any],
    config_path: Path,
) -> None:
    """
    Write a sub-run config to a YAML file.

    Args:
        config: The config dict to write
        config_path: Path to write the YAML file
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False)
    logger.debug(f"[SubrunConfig] Wrote config to {config_path}")
