#!/usr/bin/env python3
"""Gemini CLI hook script — standalone subprocess invoked by Gemini CLI.

This script is called by Gemini CLI as a subprocess for BeforeTool/AfterTool
hook events. It reads JSON from stdin (the hook event), checks for a payload
file written by the MassGen orchestrator, and returns a JSON response on stdout.

IMPORTANT: This script must NOT import from massgen — it runs as an isolated
subprocess in the Gemini CLI process, potentially inside Docker where massgen
is not installed. All logic must be self-contained.

Usage (configured in .gemini/settings.json):
    python3 gemini_cli_hook_script.py --hook-dir /path/to/.gemini --event AfterTool

Hook event JSON (stdin):
    {"tool_name": "read_file", "tool_input": {"file_path": "foo.txt"}, "tool_response": "..."}

Response JSON (stdout):
    {} — allow without modifications
    {"hookSpecificOutput": {"additionalContext": "..."}} — inject content after tool result
    {"decision": "deny", "reason": "..."} — deny the tool call (BeforeTool only)
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="MassGen hook script for Gemini CLI")
    parser.add_argument("--hook-dir", required=True, help="Directory containing hook payload files")
    parser.add_argument("--event", required=True, choices=["BeforeTool", "AfterTool"], help="Hook event type")
    args = parser.parse_args()

    hook_dir = Path(args.hook_dir)
    event = args.event

    # Read hook event from stdin
    tool_event = {}
    try:
        stdin_data = sys.stdin.read()
        if stdin_data.strip():
            parsed = json.loads(stdin_data)
            if isinstance(parsed, dict):
                tool_event = parsed
        else:
            pass
    except (json.JSONDecodeError, OSError):
        pass

    if event == "BeforeTool":
        permission_result = _evaluate_permission_manifest(hook_dir, tool_event)
        if permission_result is not None:
            _emit(permission_result)
            return

    # Check for payload file
    payload_file = hook_dir / "hook_payload.json"
    try:
        if not payload_file.exists():
            _emit({})
            return

        payload_text = payload_file.read_text(encoding="utf-8")
        payload = json.loads(payload_text)

        # Check expiration
        expires_at = payload.get("expires_at", 0)
        if expires_at and time.time() > expires_at:
            # Expired — clean up and allow
            payload_file.unlink(missing_ok=True)
            _emit({})
            return

        # Check event match
        payload_event = payload.get("event", "AfterTool")
        if payload_event != event:
            # Wrong event type — don't consume, pass through
            _emit({})
            return

        # Consume the payload (delete after reading)
        payload_file.unlink(missing_ok=True)

        # Extract injection content
        inject = payload.get("inject", {})
        content = inject.get("content", "")

        if not content:
            _emit({})
            return

        if event == "AfterTool":
            _emit({"hookSpecificOutput": {"additionalContext": content}})
        elif event == "BeforeTool":
            # BeforeTool can inject context or deny
            strategy = inject.get("strategy", "tool_result")
            if strategy == "deny":
                _emit({"decision": "deny", "reason": content})
            else:
                _emit({"additionalContext": content})

    except (json.JSONDecodeError, OSError):
        # On any error, allow the tool call to proceed
        _emit({})


def _emit(response: dict) -> None:
    """Write JSON response to stdout."""
    json.dump(response, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _evaluate_permission_manifest(hook_dir: Path, tool_event: dict) -> dict | None:
    """Return a deny decision when the serialized sandbox manifest blocks a tool call."""
    manifest_path = hook_dir / "permission_manifest.json"
    if not manifest_path.exists():
        return None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    tool_name = _extract_tool_name(tool_event)
    tool_args = _extract_tool_args(tool_event)

    allowed, reason = _validate_permission_manifest(
        tool_name=tool_name,
        tool_args=tool_args,
        manifest=manifest,
    )
    if allowed:
        return None
    return {"decision": "deny", "reason": reason or "Access denied"}


def _validate_permission_manifest(
    *,
    tool_name: str,
    tool_args: dict,
    manifest: dict,
) -> tuple[bool, str | None]:
    """Apply a small standalone subset of PathPermissionManager rules."""
    workspace = manifest.get("workspace", "")
    managed_paths = manifest.get("managed_paths", [])

    if _is_write_tool(tool_name):
        return _validate_write_tool(tool_args, workspace, managed_paths)
    if _is_command_tool(tool_name):
        return _validate_command_tool(tool_args, workspace, managed_paths)
    return _validate_read_like_tool(tool_args, workspace, managed_paths)


def _extract_tool_name(tool_event: dict) -> str:
    """Support both legacy and current Gemini CLI hook event schemas."""
    raw_name = tool_event.get("tool_name") or tool_event.get("toolName") or tool_event.get("name") or ""
    if not isinstance(raw_name, str):
        return ""
    return raw_name.rsplit("/", 1)[-1]


def _extract_tool_args(tool_event: dict) -> dict:
    """Support both legacy and current Gemini CLI hook event schemas."""
    raw_args = tool_event.get("tool_input") or tool_event.get("input") or tool_event.get("toolArgs") or tool_event.get("tool_args") or tool_event.get("arguments") or tool_event.get("parameters") or {}
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str):
        try:
            loaded = json.loads(raw_args)
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            return {}
    return {}


def _is_write_tool(tool_name: str) -> bool:
    return bool(
        re.match(r".*[Ww]rite.*", tool_name)
        or re.match(r".*[Ee]dit.*", tool_name)
        or re.match(r".*[Cc]reate.*", tool_name)
        or re.match(r".*[Mm]ove.*", tool_name)
        or re.match(r".*[Cc]opy.*", tool_name),
    )


def _is_command_tool(tool_name: str) -> bool:
    return tool_name in {"Bash", "bash", "shell", "exec", "execute_command", "run_shell_command", "shellCommand"}


def _resolve_candidate_path(path_str: str, workspace: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = Path(workspace) / path
    return path.resolve()


def _matches_managed_path(path: Path, managed_path: dict) -> bool:
    managed = Path(str(managed_path.get("path", ""))).resolve()
    if managed_path.get("is_file"):
        return path == managed
    try:
        path.relative_to(managed)
        return True
    except ValueError:
        return False


def _get_permission(path: Path, managed_paths: list[dict]) -> str | None:
    best_match: tuple[int, str] | None = None
    for managed_path in managed_paths:
        for protected_path in managed_path.get("protected_paths") or []:
            protected = Path(str(protected_path)).resolve()
            try:
                path.relative_to(protected)
                return "read"
            except ValueError:
                if path == protected:
                    return "read"

        if _matches_managed_path(path, managed_path):
            permission = managed_path.get("permission")
            if not isinstance(permission, str):
                continue
            managed = Path(str(managed_path.get("path", ""))).resolve()
            score = len(managed.parts)
            if best_match is None or score > best_match[0]:
                best_match = (score, permission)
    return best_match[1] if best_match else None


def _extract_file_path(tool_args: dict) -> str | None:
    paths_value = tool_args.get("paths")
    if isinstance(paths_value, list):
        for value in paths_value:
            if isinstance(value, str) and value:
                return value

    for key in (
        "file_path",
        "absolute_path",
        "path",
        "dir_path",
        "directory",
        "filename",
        "file",
        "notebook_path",
        "target",
        "source",
        "source_path",
        "destination",
        "destination_path",
        "destination_base_path",
        "directory",
        "dir",
    ):
        value = tool_args.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _validate_write_tool(
    tool_args: dict,
    workspace: str,
    managed_paths: list[dict],
) -> tuple[bool, str | None]:
    path_str = _extract_file_path(tool_args)
    if not path_str:
        return True, None

    resolved = _resolve_candidate_path(path_str, workspace)
    permission = _get_permission(resolved, managed_paths)
    if permission == "write":
        return True, None
    if permission == "read":
        return False, f"Command would modify read-only context path: {resolved}"
    return False, f"Access denied: {resolved} is outside allowed directories"


def _validate_read_like_tool(
    tool_args: dict,
    workspace: str,
    managed_paths: list[dict],
) -> tuple[bool, str | None]:
    path_str = _extract_file_path(tool_args)
    if not path_str:
        return True, None

    resolved = _resolve_candidate_path(path_str, workspace)
    permission = _get_permission(resolved, managed_paths)
    if permission in {"read", "write"}:
        return True, None
    return False, f"Access denied: {resolved} is outside allowed directories"


def _extract_paths_from_command(command: str) -> list[str]:
    """Extract obvious absolute and relative paths from a shell command."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    seen: set[str] = set()
    paths: list[str] = []

    def _add(p: str) -> None:
        if p not in seen:
            seen.add(p)
            paths.append(p)

    for token in tokens:
        cleaned = token.strip("\"'").strip()
        if not cleaned or cleaned.startswith("-") or cleaned in {"&&", "||", "|", ";", ">"}:
            continue
        if cleaned.startswith("/") or cleaned.startswith("~") or cleaned.startswith("../") or cleaned == ".." or cleaned.startswith("./"):
            _add(cleaned)

    # Also extract absolute paths embedded in quoted strings.
    # This catches python3 -c "open('/path', 'w')" style sandbox bypasses.
    for match in re.finditer(r"(?<=['\"])(/[^'\"]+)", command):
        embedded = match.group(1).rstrip("/")
        if len(embedded) > 1:
            _add(embedded)

    return paths


def _command_likely_writes(command: str) -> bool:
    lowered = command.lower()
    indicators = (
        ">",
        ">>",
        " tee ",
        " touch ",
        " mkdir ",
        " mv ",
        " cp ",
        " rm ",
        " sed -i",
        " perl -i",
    )
    return any(indicator in lowered for indicator in indicators)


def _validate_command_tool(
    tool_args: dict,
    workspace: str,
    managed_paths: list[dict],
) -> tuple[bool, str | None]:
    command = tool_args.get("command") or tool_args.get("cmd") or ""
    if not isinstance(command, str) or not command:
        return True, None

    if "$(" in command or "${" in command or "`" in command or "<(" in command or ">(" in command:
        return False, "Command substitution and process substitution are not allowed"

    command_writes = _command_likely_writes(command)
    dir_path = tool_args.get("dir_path") or tool_args.get("directory") or tool_args.get("cwd") or workspace
    if not isinstance(dir_path, str) or not dir_path:
        dir_path = workspace

    resolved_dir = _resolve_candidate_path(dir_path, workspace)
    dir_permission = _get_permission(resolved_dir, managed_paths)
    if dir_permission not in {"read", "write"}:
        return (
            False,
            f"Access denied: Shell command dir_path resolves to '{resolved_dir}' outside allowed directories",
        )
    if command_writes and dir_permission != "write":
        return False, f"Command would modify read-only context path: {resolved_dir}"

    for path_str in _extract_paths_from_command(command):
        resolved = _resolve_candidate_path(path_str, str(resolved_dir))
        permission = _get_permission(resolved, managed_paths)
        if permission not in {"read", "write"}:
            return (
                False,
                f"Access denied: Bash command references '{path_str}' which resolves to '{resolved}' outside allowed directories",
            )
        if command_writes and permission != "write":
            return False, f"Command would modify read-only context path: {resolved}"

    return True, None


if __name__ == "__main__":
    main()
