"""Tool categorization and display utilities.

Single source of truth for tool category definitions, icons, colors, and
display formatting. Previously duplicated across:
- textual_terminal_display.py:183-330
- content_handlers.py:90
- textual_widgets/tool_card.py:87

This consolidation ensures consistent tool display across main TUI and
subprocess displays (SubagentCard, SubagentTuiModal, SubagentScreen).
"""

import ast
import json

# Tool category detection - maps tool names to semantic categories
# Icons removed - rely on color-coded left border for category indication
TOOL_CATEGORIES = {
    "filesystem": {
        "color": "#5a9d8a",  # Softer teal
        "patterns": [
            "read_file",
            "write_file",
            "list_directory",
            "create_directory",
            "delete_file",
            "move_file",
            "copy_file",
            "file_exists",
            "get_file_info",
            "read_multiple_files",
            "edit_file",
            "directory_tree",
            "search_files",
            "find_files",
            "mcp__filesystem",
            "read_text_file",
            "write_text_file",
            "list_allowed_directories",
            "codex_file_edit",
        ],
    },
    "web": {
        "color": "#6a8db0",  # Softer blue
        "patterns": [
            "web_search",
            "search_web",
            "google_search",
            "fetch_url",
            "http_request",
            "browse",
            "scrape",
            "download",
            "http_get",
            "http_post",
            "crawl",
            "mcp__brave",
            "mcp__web",
            "mcp__fetch",
            "codex_web_search",
            "codex_image_view",
        ],
    },
    "code": {
        "color": "#b8b896",  # Softer yellow
        "patterns": [
            "execute_command",
            "run_code",
            "bash",
            "python",
            "shell",
            "terminal",
            "exec",
            "run_script",
            "execute",
            "execute_python",
            "command",
            "mcp__code",
            "mcp__shell",
            "mcp__terminal",
            "codex_shell",
        ],
    },
    "database": {
        "color": "#a67db0",  # Softer purple
        "patterns": [
            "query",
            "sql",
            "database",
            "db_",
            "select",
            "insert",
            "update",
            "delete_record",
            "mcp__postgres",
            "mcp__sqlite",
            "mcp__mysql",
            "mcp__mongo",
            "arbitrary_query",
            "schema_reference",
        ],
    },
    "git": {
        "color": "#c06050",  # Softer red
        "patterns": [
            "git_",
            "commit",
            "push",
            "pull",
            "clone",
            "branch",
            "merge",
            "checkout",
            "diff",
            "log",
            "status",
            "mcp__git",
        ],
    },
    "api": {
        "color": "#a88068",  # Softer orange
        "patterns": [
            "api_",
            "request",
            "post",
            "get",
            "put",
            "patch",
            "rest",
            "graphql",
            "endpoint",
            "rest_",
            "mcp__slack",
            "mcp__discord",
            "mcp__twitter",
            "mcp__notion",
        ],
    },
    "ai": {
        "color": "#7ab0d0",  # Softer cyan
        "patterns": [
            "generate",
            "complete",
            "chat",
            "embed",
            "model",
            "inference",
            "predict",
            "classify",
            "llm_",
            "ai_",
            "chat_completion",
            "mcp__openai",
            "mcp__anthropic",
            "mcp__gemini",
        ],
    },
    "memory": {
        "color": "#90b088",  # Softer green
        "patterns": [
            "memory",
            "remember",
            "recall",
            "store",
            "retrieve",
            "knowledge",
            "context",
            "mcp__memory",
        ],
    },
    "workspace": {
        "color": "#50a8c8",  # Softer blue
        "patterns": [
            "workspace",
            "new_answer",
            "vote",
            "answer",
            "coordination",
        ],
    },
    "human_input": {
        "color": "#b89040",  # Softer gold
        "patterns": [
            "human_input",
            "user_input",
            "injected_input",
        ],
    },
    "subagent": {
        "color": "#9070c0",  # Softer purple
        "patterns": [
            "spawn_subagent",
            "subagent",
            "list_subagents",
            "continue_subagent",
        ],
    },
    "weather": {
        "color": "#70b8d8",  # Softer cyan
        "patterns": [
            "weather",
            "forecast",
            "temperature",
            "get-forecast",
            "mcp__weather",
        ],
    },
    "checkpoint": {
        "color": "#d4a050",  # Warm gold - coordination checkpoint
        "patterns": [
            "checkpoint",
        ],
    },
}


def get_tool_category(tool_name: str) -> dict:
    """Get category info for a tool name.

    Args:
        tool_name: The tool name to categorize.

    Returns:
        Dict with color and category name.
    """
    tool_lower = tool_name.lower()

    # Check MCP tools (format: mcp__server__tool)
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        if len(parts) >= 3:
            actual_tool = parts[-1]
            tool_lower = actual_tool.lower()

    # Check against category patterns
    for category_name, info in TOOL_CATEGORIES.items():
        for pattern in info["patterns"]:
            if pattern in tool_lower:
                return {
                    "color": info["color"],
                    "category": category_name,
                }

    # Default to generic tool
    return {"color": "#858585", "category": "tool"}


def is_terminal_tool(tool_name: str) -> bool:
    """Whether a tool deserves the "hero" card treatment.

    Terminal tools like `new_answer`, `vote`, and `checkpoint` are the
    culmination of an agent's work and render as a prominent expanded
    card rather than a one-line collapsed entry. Used by both
    `ToolCallCard._detect_terminal_tool` (for individual rendering) and
    `ToolBatchTracker.process_tool` (to keep a hero tool from being
    silently nested inside a batch card).

    The standalone checkpoint server exposes both `init` (housekeeping,
    one-time session setup) and `checkpoint` (the heavy delegation). Only
    `checkpoint` deserves the hero card.
    """
    name_lower = tool_name.lower()
    if name_lower.endswith("__init") and "checkpoint" in name_lower:
        return False
    return any(t in name_lower for t in ("new_answer", "vote", "checkpoint"))


def format_tool_display_name(tool_name: str) -> str:
    """Format tool name for display.

    Args:
        tool_name: Raw tool name.

    Returns:
        Formatted display name.
    """
    # Handle MCP tools: mcp__server__tool -> server/tool
    # Custom tools have extra segments: mcp__server__custom_tool__actual_name
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        if len(parts) >= 4 and parts[2] == "custom_tool":
            # mcp__server__custom_tool__name -> server/name
            return f"{parts[1]}/{'__'.join(parts[3:])}"
        elif len(parts) >= 3:
            return f"{parts[1]}/{parts[2]}"
        elif len(parts) == 2:
            return parts[1]

    # Handle snake_case
    return tool_name.replace("_", " ").title()


def clean_tool_arguments(args_str: str) -> str:
    """Clean up tool arguments for display - extract key info from dicts/JSON.

    Args:
        args_str: Raw arguments string (may be dict repr or JSON)

    Returns:
        Clean, readable summary of the arguments
    """
    args_str = args_str.strip()

    # Try to parse as JSON/dict
    try:
        # Handle dict-like strings
        if args_str.startswith("{") or args_str.startswith("Arguments:"):
            clean = args_str.replace("Arguments:", "").strip()
            # Try JSON parse
            try:
                data = json.loads(clean)
            except json.JSONDecodeError:
                # Try eval for dict repr (safely)
                try:
                    data = ast.literal_eval(clean)
                except (ValueError, SyntaxError):
                    data = None

            if isinstance(data, dict):
                # Extract key fields for nice display
                parts = []
                for key, value in data.items():
                    # Skip long content fields
                    if key in ("content", "body", "text", "data") and isinstance(value, str) and len(value) > 50:
                        parts.append(f"{key}: [{len(value)} chars]")
                    # Shorten paths
                    elif key in ("path", "file", "directory", "work_dir") and isinstance(value, str):
                        # Show just filename or last part of path
                        short_path = value.split("/")[-1] if "/" in value else value
                        if len(value) > 40:
                            parts.append(f"{key}: .../{short_path}")
                        else:
                            parts.append(f"{key}: {value}")
                    # Truncate command
                    elif key == "command" and isinstance(value, str):
                        if len(value) > 60:
                            parts.append(f"{key}: {value[:60]}...")
                        else:
                            parts.append(f"{key}: {value}")
                    # Skip internal fields
                    elif key.startswith("_"):
                        continue
                    # Show other fields truncated
                    elif isinstance(value, str) and len(value) > 50:
                        parts.append(f"{key}: {value[:50]}...")
                    elif isinstance(value, (list, dict)):
                        parts.append(f"{key}: [{type(value).__name__}]")
                    else:
                        parts.append(f"{key}: {value}")

                if parts:
                    return " | ".join(parts[:3])  # Max 3 fields
                return "[no args]"
    except Exception:
        pass

    # Fallback: just truncate
    if len(args_str) > 80:
        return args_str[:80] + "..."
    return args_str


def clean_tool_result(result_str: str, tool_name: str = "") -> str:
    """Clean up tool result for display - summarize long output.

    Args:
        result_str: Raw result string
        tool_name: Tool name for context-aware formatting

    Returns:
        Clean, readable summary of the result
    """
    result_str = result_str.strip()

    # Handle common MCP result formats
    if result_str.startswith("{"):
        try:
            data = json.loads(result_str)
            if isinstance(data, dict):
                # Check for success/error status
                if "success" in data:
                    status = "✓" if data["success"] else "✗"
                    if "message" in data:
                        return f"{status} {data['message'][:60]}"
                    return f"{status} {'Success' if data['success'] else 'Failed'}"

                # Extract content field
                if "content" in data:
                    content = str(data["content"])
                    if len(content) > 100:
                        return f"{content[:100]}..."
                    return content

                # Extract error field
                if "error" in data:
                    return f"✗ {data['error'][:60]}"
        except json.JSONDecodeError:
            pass

    # Truncate long results
    lines = result_str.split("\n")
    if len(lines) > 5:
        preview = "\n".join(lines[:5])
        return f"{preview}\n... [{len(lines) - 5} more lines]"

    if len(result_str) > 200:
        return result_str[:200] + "..."

    return result_str
