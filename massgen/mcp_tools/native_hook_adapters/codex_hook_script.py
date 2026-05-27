#!/usr/bin/env python3
"""Standalone Codex hook script.

This script runs as an external subprocess invoked by Codex hooks. It must
remain self-contained because Codex may execute it outside the MassGen Python
environment, including inside Docker.

Supported behavior:
- ``PreToolUse``: deny Bash commands using a serialized permission manifest
- ``PostToolUse``: consume ``hook_post_tool_use.json`` and inject developer
  context after Bash tool results
- lifecycle events currently return an empty JSON object
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shlex
import sys
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="MassGen hook script for Codex")
    parser.add_argument("--hook-dir", required=True, help="Directory containing hook payload files")
    parser.add_argument(
        "--event",
        required=True,
        choices=["SessionStart", "PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop"],
        help="Codex hook event type",
    )
    args = parser.parse_args()

    hook_dir = Path(args.hook_dir)
    event = args.event

    tool_event: dict[str, object] = {}
    try:
        stdin_data = sys.stdin.read()
        if stdin_data.strip():
            parsed = json.loads(stdin_data)
            if isinstance(parsed, dict):
                tool_event = parsed
    except (json.JSONDecodeError, OSError):
        tool_event = {}

    if event == "PreToolUse":
        permission_result = _evaluate_permission_manifest(hook_dir, tool_event)
        if permission_result is not None:
            _emit(permission_result)
            return

    if event != "PostToolUse":
        _emit({})
        return

    payload_path = hook_dir / "hook_post_tool_use.json"
    try:
        if not payload_path.exists():
            _emit({})
            return

        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        expires_at = payload.get("expires_at", 0)
        if expires_at and time.time() > expires_at:
            payload_path.unlink(missing_ok=True)
            _emit({})
            return

        tool_name = _extract_tool_name(tool_event)
        matcher = payload.get("tool_matcher", "*")
        if not _matches_tool(tool_name, matcher):
            _emit({})
            return

        payload_path.unlink(missing_ok=True)
        inject = payload.get("inject", {})
        content = inject.get("content", "")
        if not isinstance(content, str) or not content:
            _emit({})
            return

        _emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": content,
                },
            },
        )
    except (json.JSONDecodeError, OSError):
        payload_path.unlink(missing_ok=True)
        _emit({})


def _emit(response: dict[str, object]) -> None:
    json.dump(response, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _matches_tool(tool_name: str, matcher: object) -> bool:
    if not isinstance(matcher, str) or not matcher or matcher == "*":
        return True
    patterns = [pattern.strip() for pattern in matcher.split("|") if pattern.strip()]
    if not patterns:
        return True
    return any(fnmatch.fnmatch(tool_name, pattern) for pattern in patterns)


def _evaluate_permission_manifest(
    hook_dir: Path,
    tool_event: dict[str, object],
) -> dict[str, object] | None:
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
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason or "Access denied",
        },
    }


def _validate_permission_manifest(
    *,
    tool_name: str,
    tool_args: dict[str, object],
    manifest: dict[str, object],
) -> tuple[bool, str | None]:
    workspace = str(manifest.get("workspace", ""))
    managed_paths = manifest.get("managed_paths", [])
    if not isinstance(managed_paths, list):
        managed_paths = []

    if _is_command_tool(tool_name):
        return _validate_command_tool(tool_args, workspace, managed_paths)
    return True, None


def _extract_tool_name(tool_event: dict[str, object]) -> str:
    raw_name = tool_event.get("tool_name") or tool_event.get("toolName") or tool_event.get("name") or ""
    if not isinstance(raw_name, str):
        return ""
    return raw_name.rsplit("/", 1)[-1]


def _extract_tool_args(tool_event: dict[str, object]) -> dict[str, object]:
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


def _is_command_tool(tool_name: str) -> bool:
    return tool_name in {
        "Bash",
        "bash",
        "shell",
        "exec",
        "execute_command",
        "run_shell_command",
        "shellCommand",
    }


def _resolve_candidate_path(path_str: str, workspace: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = Path(workspace) / path
    return path.resolve()


def _matches_managed_path(path: Path, managed_path: dict[str, object]) -> bool:
    managed = Path(str(managed_path.get("path", ""))).resolve()
    if managed_path.get("is_file"):
        return path == managed
    try:
        path.relative_to(managed)
        return True
    except ValueError:
        return False


def _get_permission(path: Path, managed_paths: list[dict[str, object]]) -> str | None:
    best_match: tuple[int, str] | None = None
    for managed_path in managed_paths:
        protected_paths = managed_path.get("protected_paths") or []
        if isinstance(protected_paths, list):
            for protected_path in protected_paths:
                protected = Path(str(protected_path)).resolve()
                try:
                    path.relative_to(protected)
                    return "read"
                except ValueError:
                    if path == protected:
                        return "read"

        if _matches_managed_path(path, managed_path):
            permission = managed_path.get("permission")
            if isinstance(permission, str):
                managed = Path(str(managed_path.get("path", ""))).resolve()
                score = len(managed.parts)
                if best_match is None or score > best_match[0]:
                    best_match = (score, permission)
    return best_match[1] if best_match else None


def _extract_paths_from_command(command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    seen: set[str] = set()
    paths: list[str] = []

    def _add(path_str: str) -> None:
        if path_str not in seen:
            seen.add(path_str)
            paths.append(path_str)

    for token in tokens:
        cleaned = token.strip("\"'").strip()
        if not cleaned or cleaned.startswith("-") or cleaned in {"&&", "||", "|", ";", ">"}:
            continue
        if cleaned.startswith("/") or cleaned.startswith("~") or cleaned.startswith("../") or cleaned == ".." or cleaned.startswith("./"):
            _add(cleaned)

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
    tool_args: dict[str, object],
    workspace: str,
    managed_paths: list[dict[str, object]],
) -> tuple[bool, str | None]:
    raw_command = tool_args.get("command") or tool_args.get("cmd") or ""
    if not isinstance(raw_command, str) or not raw_command:
        return True, None

    if "$(" in raw_command or "${" in raw_command or "`" in raw_command or "<(" in raw_command or ">(" in raw_command:
        return False, "Command substitution and process substitution are not allowed"

    command_writes = _command_likely_writes(raw_command)
    dir_path = tool_args.get("cwd") or tool_args.get("dir_path") or tool_args.get("directory") or workspace
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

    for path_str in _extract_paths_from_command(raw_command):
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
