"""
Content Handlers for MassGen TUI.

Type-specific processing logic for different content types.
Each handler processes normalized content and returns display-ready data.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .content_normalizer import ContentNormalizer, NormalizedContent
from .shared import get_tool_category as shared_get_tool_category
from .shared.tool_registry import (  # noqa: F401 - re-export
    format_tool_display_name,
    is_terminal_tool,
)
from .shared.tui_debug import tui_log


def get_mcp_server_name(tool_name: str) -> str | None:
    """Extract MCP server name from mcp__server__tool format.

    Args:
        tool_name: The full tool name (e.g., "mcp__filesystem__write_file").

    Returns:
        Server name if this is an MCP tool (e.g., "filesystem"), None otherwise.
    """
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        if len(parts) >= 2:
            return parts[1]
    return None


def get_mcp_tool_name(tool_name: str) -> str | None:
    """Extract the actual tool name from mcp__server__tool format.

    Handles custom tools: mcp__server__custom_tool__name -> name

    Args:
        tool_name: The full tool name (e.g., "mcp__filesystem__write_file").

    Returns:
        Tool name if this is an MCP tool (e.g., "write_file"), None otherwise.
    """
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        if len(parts) >= 4 and parts[2] == "custom_tool":
            return "__".join(parts[3:])
        if len(parts) >= 3:
            return parts[2]
    return None


@dataclass
class ToolDisplayData:
    """Data for displaying a tool call."""

    tool_id: str
    tool_name: str
    display_name: str
    tool_type: str
    category: str
    icon: str
    color: str
    status: str  # running, success, error, background
    start_time: datetime
    end_time: datetime | None = None
    args_summary: str | None = None  # Truncated for card display
    args_full: str | None = None  # Full args for modal
    result_summary: str | None = None  # Truncated for card display
    result_full: str | None = None  # Full result for modal
    error: str | None = None
    elapsed_seconds: float | None = None
    async_id: str | None = None  # ID for background operations (e.g., shell_id)
    server_name: str | None = None  # Server name from event (e.g., "codex", "filesystem")


# Tool category utilities imported from shared module


def get_tool_category(tool_name: str) -> dict[str, str]:
    """Get category info for a tool name.

    Wrapper around shared.get_tool_category() that adds 'icon' field
    for backwards compatibility with this module's existing code.
    """
    result = shared_get_tool_category(tool_name)
    # Add default icon since shared version doesn't include icons
    icon_map = {
        "filesystem": "📁",
        "web": "🌐",
        "code": "💻",
        "database": "🗄️",
        "git": "📦",
        "api": "🔌",
        "ai": "🤖",
        "memory": "🧠",
        "workspace": "📝",
        "human_input": "💬",
        "weather": "🌤️",
        "subagent": "🔗",
        "checkpoint": "🏁",
        "tool": "🔧",
    }
    result["icon"] = icon_map.get(result.get("category", "tool"), "🔧")
    return result


def summarize_args(args: dict[str, Any], max_len: int = 80) -> str:
    """Summarize tool arguments for display."""
    if not args:
        return ""

    parts = []
    for key, value in args.items():
        if isinstance(value, str):
            if len(value) > 30:
                value = value[:27] + "..."
            parts.append(f"{key}: {value}")
        elif isinstance(value, (int, float, bool)):
            parts.append(f"{key}: {value}")
        elif isinstance(value, (list, dict)):
            parts.append(f"{key}: [{type(value).__name__}]")

    result = ", ".join(parts)
    if len(result) > max_len:
        result = result[: max_len - 3] + "..."
    return result


def summarize_result(result: str, max_len: int = 100) -> str:
    """Summarize tool result for display."""
    if not result:
        return ""

    # Strip injection markers that may appear in tool results
    result = ContentNormalizer.strip_injection_markers(result)

    # Count lines
    lines = result.split("\n")
    line_count = len(lines)

    # Get first meaningful line
    first_line = ""
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("{") and not stripped.startswith("["):
            first_line = stripped
            break

    if not first_line:
        first_line = lines[0].strip() if lines else ""

    # Truncate if needed
    if len(first_line) > max_len:
        first_line = first_line[: max_len - 3] + "..."

    # Add line count indicator
    if line_count > 1:
        return f"{first_line} [{line_count} lines]"
    return first_line


class BaseContentHandler(ABC):
    """Base class for content handlers."""

    @abstractmethod
    def process(self, normalized: NormalizedContent) -> Any:
        """Process normalized content.

        Args:
            normalized: Normalized content from ContentNormalizer

        Returns:
            Handler-specific result, or None to filter out
        """


class ThinkingContentHandler(BaseContentHandler):
    """Handler for thinking/reasoning content.

    Filters JSON noise and cleans up streaming content.
    """

    # Additional patterns to filter beyond what normalizer catches
    EXTRA_FILTER_PATTERNS = [
        r"^\s*[\{\}]\s*$",  # Lone braces
        r"^\s*[\[\]]\s*$",  # Lone brackets
        r'^\s*"[^"]*"\s*:\s*$',  # JSON keys
        r"^\s*,\s*$",  # Lone commas
    ]

    def __init__(self):
        self._compiled_filters = [re.compile(p) for p in self.EXTRA_FILTER_PATTERNS]

    def process(self, normalized: NormalizedContent) -> str | None:
        """Process thinking content and return cleaned text."""
        if not normalized.should_display:
            return None

        content = normalized.cleaned_content

        # Additional filtering
        for pattern in self._compiled_filters:
            if pattern.match(content):
                return None

        # Clean up bullet points if they're lone bullets
        if content.strip() in ("•", "-", "*", "·"):
            return None

        return content


class StatusContentHandler(BaseContentHandler):
    """Handler for status content.

    Extracts status type and returns minimal display data.
    """

    STATUS_TYPES = {
        "connected": ("●", "green", "Connected"),
        "disconnected": ("○", "red", "Disconnected"),
        "working": ("⟳", "yellow", "Working"),
        "streaming": ("▶", "cyan", "Streaming"),
        "completed": ("✓", "green", "Complete"),
        "error": ("✗", "red", "Error"),
        "waiting": ("○", "dim", "Waiting"),
    }

    def process(self, normalized: NormalizedContent) -> dict[str, str] | None:
        """Process status content and return display info."""
        content_lower = normalized.cleaned_content.lower()

        # Detect status type
        status_type = "unknown"
        if "completed" in content_lower or "complete" in content_lower:
            status_type = "completed"
        elif "working" in content_lower:
            status_type = "working"
        elif "streaming" in content_lower:
            status_type = "streaming"
        elif "error" in content_lower or "failed" in content_lower:
            status_type = "error"
        elif "connected" in content_lower:
            status_type = "connected"
        elif "waiting" in content_lower:
            status_type = "waiting"

        if status_type in self.STATUS_TYPES:
            icon, color, label = self.STATUS_TYPES[status_type]
            return {
                "type": status_type,
                "icon": icon,
                "color": color,
                "label": label,
            }

        return None


class PresentationContentHandler(BaseContentHandler):
    """Handler for final presentation content."""

    def process(self, normalized: NormalizedContent) -> str | None:
        """Process presentation content."""
        if not normalized.should_display:
            return None

        content = normalized.cleaned_content

        # Filter "Providing answer:" prefix (may have emoji like 💡)
        if "Providing answer:" in content:
            return None

        return content


class ToolBatchTracker:
    """Tracks consecutive MCP tool calls for batching into tree views.

    Only batches when 2+ consecutive tools from the same server arrive.
    Single tools appear as normal ToolCallCard with fade-in animation.

    Flow:
    1. First MCP tool → show as normal ToolCallCard, track as "pending"
    2. Second consecutive tool from same server → convert to batch
    3. More tools from same server → add to batch
    4. Different server or non-MCP → finalize, start fresh
    """

    def __init__(self):
        self._current_server: str | None = None
        self._current_batch_id: str | None = None
        self._pending_tool_id: str | None = None  # First tool, not yet batched
        self._batch_counter = 0
        self._batched_tool_ids: set = set()  # Track which tools are in batches
        self._content_since_last_tool: bool = False  # True if non-tool content arrived

    def mark_content_arrived(self) -> None:
        """Mark that non-tool content (thinking, text, status) has arrived.

        This is used to prevent batching tools that have content between them.
        Called whenever non-tool content is added to the timeline.
        """
        self._content_since_last_tool = True

    def process_tool(self, tool_data: ToolDisplayData) -> tuple[str, str | None, str | None, str | None]:
        """Determine how to handle an incoming tool call.

        Returns:
            Tuple of (action, server_name, batch_id, pending_tool_id) where action is:
            - "standalone": Non-MCP tool, use regular ToolCallCard
            - "pending": First MCP tool, show as ToolCallCard but track for potential batch
            - "convert_to_batch": Second tool arrived - convert pending to batch
            - "add_to_batch": Add to existing batch
            - "update_standalone": Update a standalone/pending tool
            - "update_batch": Update existing tool in batch
        """
        # If content arrived since last tool, finalize batch and start fresh
        # This ensures chronological order is respected in the timeline
        if self._content_since_last_tool and tool_data.status == "running":
            self._finalize_pending()
            self._content_since_last_tool = False

        server_name = get_mcp_server_name(tool_data.tool_name)
        # Fallback to event-provided server_name for non-mcp__ prefixed tools
        if server_name is None and tool_data.server_name:
            server_name = tool_data.server_name

        # Tools without any server context get standalone treatment
        if server_name is None:
            self._finalize_pending()
            result = ("standalone", None, None, None)
            tui_log(
                f"[BATCH] tool={tool_data.tool_name} mcp_server=None "
                f"event_server={tool_data.server_name} "
                f"pending={self._pending_tool_id} current_server={self._current_server} "
                f"content_since_last={self._content_since_last_tool} "
                f"-> action=standalone",
            )
            return result

        # Check if this is an update (not "running")
        if tool_data.status != "running":
            if tool_data.tool_id in self._batched_tool_ids:
                action = "update_batch"
            else:
                action = "update_standalone"
            tui_log(
                f"[BATCH] tool={tool_data.tool_name} mcp_server={server_name} " f"status={tool_data.status} -> action={action}",
            )
            if action == "update_batch":
                return ("update_batch", server_name, self._current_batch_id, None)
            return ("update_standalone", server_name, None, None)

        # New tool starting (status == "running")

        # Hero/terminal tools (`checkpoint`, `new_answer`, `vote`) must
        # never be silently nested inside a batch card — they own their
        # own expanded standalone rendering. Finalize any pending batch
        # first so the previous tools render as standalone cards, then
        # let this hero be standalone too.
        if is_terminal_tool(tool_data.tool_name):
            self._finalize_pending()
            self._current_server = server_name
            self._pending_tool_id = tool_data.tool_id
            tui_log(
                f"[BATCH] tool={tool_data.tool_name} mcp_server={server_name} " f"-> action=pending (terminal/hero tool, never batched)",
            )
            return ("pending", server_name, None, None)

        # Already have an active batch for this server?
        if self._current_batch_id and self._current_server == server_name:
            self._batched_tool_ids.add(tool_data.tool_id)
            tui_log(
                f"[BATCH] tool={tool_data.tool_name} mcp_server={server_name} " f"batch_id={self._current_batch_id} -> action=add_to_batch",
            )
            return ("add_to_batch", server_name, self._current_batch_id, None)

        # Have a pending tool from same server? → Convert to batch
        if self._pending_tool_id and self._current_server == server_name:
            self._batch_counter += 1
            self._current_batch_id = f"batch_{self._batch_counter}"
            pending_id = self._pending_tool_id
            self._batched_tool_ids.add(pending_id)
            self._batched_tool_ids.add(tool_data.tool_id)
            self._pending_tool_id = None
            tui_log(
                f"[BATCH] tool={tool_data.tool_name} mcp_server={server_name} " f"batch_id={self._current_batch_id} pending_id={pending_id} " f"-> action=convert_to_batch",
            )
            return ("convert_to_batch", server_name, self._current_batch_id, pending_id)

        # Different server or first tool → finalize and track as pending
        self._finalize_pending()
        self._current_server = server_name
        self._pending_tool_id = tool_data.tool_id
        tui_log(
            f"[BATCH] tool={tool_data.tool_name} mcp_server={server_name} " f"-> action=pending (first tool from this server)",
        )
        return ("pending", server_name, None, None)

    def _finalize_pending(self) -> None:
        """Finalize any pending tool (it stays as standalone)."""
        self._pending_tool_id = None
        self._current_server = None
        self._current_batch_id = None

    def finalize_current_batch(self) -> str | None:
        """Called when non-tool content arrives to finalize tracking."""
        finalized_id = self._current_batch_id
        self._finalize_pending()
        return finalized_id

    def reset(self) -> None:
        """Reset the tracker state (e.g., for new round)."""
        self._current_server = None
        self._current_batch_id = None
        self._pending_tool_id = None
        self._batched_tool_ids.clear()  # Clear accumulated tool IDs to prevent memory growth
        self._content_since_last_tool = False

    @property
    def current_batch_id(self) -> str | None:
        """Get the current batch ID if any."""
        return self._current_batch_id

    @property
    def current_server(self) -> str | None:
        """Get the current server name if batching."""
        return self._current_server
