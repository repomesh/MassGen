"""
Tool Call Card Widget for MassGen TUI.

Provides clickable cards for displaying tool calls with their
parameters, results, and status. Clicking opens a detail modal.
"""

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Click
from textual.message import Message
from textual.widgets import Static

from massgen.frontend.displays.shared import format_tool_display_name, get_tool_category

if TYPE_CHECKING:
    pass


class InjectionToggle(Static):
    """Clickable widget for toggling injection content expansion.

    This widget handles its own click event to toggle expansion,
    preventing the click from bubbling up to the parent ToolCallCard.
    """

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    def __init__(
        self,
        content: Text,
        toggle_callback: Callable[[], None],
        *,
        id: str | None = None,
    ) -> None:
        """Initialize the injection toggle.

        Args:
            content: The Rich Text content to display.
            toggle_callback: Callback to invoke when clicked.
            id: Optional DOM ID.
        """
        super().__init__(id=id)
        self._content = content
        self._toggle_callback = toggle_callback

    def render(self) -> Text:
        """Render the injection toggle content."""
        return self._content

    def update_content(self, content: Text) -> None:
        """Update the displayed content."""
        self._content = content
        self.refresh()

    def on_click(self, event: Click) -> None:
        """Handle click - toggle injection and stop propagation."""
        from massgen.logger_config import logger

        logger.info("[InjectionToggle] on_click triggered!")
        event.stop()  # Prevent bubbling to parent ToolCallCard
        self._toggle_callback()
        logger.info("[InjectionToggle] callback completed")


# Tool category utilities imported from shared module


# get_tool_category imported from shared module


# format_tool_display_name imported from shared module


class ToolCallCard(Static):
    """Clickable card showing a tool call with status, params, and result.

    Clicking the card posts a ToolCardClicked message that can be
    handled to show a detail modal.

    Attributes:
        tool_name: Name of the tool being called.
        tool_type: Type of tool (mcp, custom, etc.).
        status: Current status (running, success, error).
    """

    class ToolCardClicked(Message):
        """Posted when a tool card is clicked."""

        def __init__(self, card: "ToolCallCard") -> None:
            self.card = card
            super().__init__()

    # Enable clicking on the widget
    can_focus = True

    STATUS_ICONS = {
        "running": "◉",  # Solid circle - non-emoji for running
        "success": "✓",  # Keep checkmark
        "error": "✗",  # Keep X mark
        "background": "○",  # Hollow circle for async/background operations
    }

    def __init__(
        self,
        tool_name: str,
        tool_type: str = "unknown",
        call_id: str | None = None,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the tool card.

        Args:
            tool_name: Name of the tool.
            tool_type: Type (mcp, custom, etc.).
            call_id: Optional unique call identifier.
            id: Optional DOM ID.
            classes: Optional CSS classes.
        """
        super().__init__(id=id, classes=classes)
        self.tool_name = tool_name
        self.tool_type = tool_type
        self.call_id = call_id
        self._status = "running"
        self._start_time = datetime.now()
        self._end_time: datetime | None = None
        self._params: str | None = None  # Truncated for display
        self._params_full: str | None = None  # Full args for modal
        self._result: str | None = None  # Truncated for display
        self._result_full: str | None = None  # Full result for modal
        self._error: str | None = None

        # Get category info for styling
        self._category = get_tool_category(tool_name)
        self._display_name = format_tool_display_name(tool_name)

        # Add type class for styling
        self.add_class(f"type-{self._category['category']}")
        self.add_class("status-running")

        # Hook execution tracking (for display in TUI)
        self._pre_hooks: list = []  # Hooks that ran before tool
        self._post_hooks: list = []  # Hooks that ran after tool
        self._injection_expanded: bool = False  # Track if injection content is expanded

        # Collapsed state for non-subagent cards (default collapsed for cleaner UI)
        self._collapsed: bool = True

        # Subagent-specific state
        self._is_subagent = self._category["category"] == "subagent"
        self._expanded = False  # For showing workspace inline
        self._subagent_tasks: list[dict] = []  # Parsed subagent task list
        self._workspace_content: str | None = None  # Subagent workspace output

        # Terminal tool detection - these are "hero" tools (new_answer, vote)
        self._is_terminal = self._detect_terminal_tool(tool_name)
        if self._is_terminal:
            self._collapsed = False  # Force expanded for terminal tools
            self.add_class("terminal-tool")

        # Injection toggle widget (managed separately for click handling)
        self._injection_toggle: InjectionToggle | None = None

        # Timer for updating elapsed time while running
        self._elapsed_timer = None

        # Background/async operation tracking
        self._async_id: str | None = None  # e.g., shell_id for background shells
        self._is_background = False  # True if this is an async operation

        # Appearance animation state
        self.add_class("appearing")  # Start in appearing state

        # Add collapsed class for non-subagent, non-terminal cards
        if not self._is_subagent and not self._is_terminal:
            self.add_class("collapsed")

    def _detect_terminal_tool(self, tool_name: str) -> bool:
        """Check if this is a terminal coordination tool (hero tool).

        Terminal tools like new_answer and vote are the culmination of an
        agent's work and deserve prominent visual treatment.

        The standalone checkpoint server exposes both `init` (housekeeping,
        called once per session) and `checkpoint` (heavy, spawns a sub-MassGen).
        Only `checkpoint` deserves the hero card; `init` should render as a
        regular collapsed MCP tool.

        Args:
            tool_name: The tool name to check.

        Returns:
            True if this is a terminal tool, False otherwise.
        """
        name_lower = tool_name.lower()
        if name_lower.endswith("__init") and "checkpoint" in name_lower:
            return False
        return any(t in name_lower for t in ("new_answer", "vote", "checkpoint"))

    def on_mount(self) -> None:
        """Start the elapsed time timer and complete appearance animation."""
        if self._status == "running":
            self._start_elapsed_timer()

        # Complete the appearance animation after a brief delay
        self.set_timer(0.3, self._complete_appearance)

    def _complete_appearance(self) -> None:
        """Complete the appearance animation by transitioning to appeared state."""
        self.remove_class("appearing")
        self.add_class("appeared")

    def on_unmount(self) -> None:
        """Stop the timer when unmounted."""
        self._stop_elapsed_timer()

    def _start_elapsed_timer(self) -> None:
        """Start periodic refresh for elapsed time display."""
        if self._elapsed_timer is None:
            # Update every 500ms - sufficient granularity for elapsed time display
            self._elapsed_timer = self.set_interval(0.5, self._refresh_elapsed)

    def _stop_elapsed_timer(self) -> None:
        """Stop the elapsed time timer."""
        if self._elapsed_timer is not None:
            self._elapsed_timer.stop()
            self._elapsed_timer = None

    def _refresh_elapsed(self) -> None:
        """Refresh the display to update elapsed time."""
        if self._status == "running":
            self._refresh_main_content()
        else:
            # Tool completed, stop the timer
            self._stop_elapsed_timer()

    def _refresh_main_content(self) -> None:
        """Refresh the main content widget."""
        try:
            main_content = self.query_one("#tool-main-content", Static)
            main_content.update(self._render_main_content())
        except Exception:
            # Fallback if widget not found (e.g., not yet mounted)
            self.refresh()

    def _refresh_injection_toggle(self) -> None:
        """Refresh the injection toggle widget if it exists."""
        if self._injection_toggle:
            self._injection_toggle.update_content(self._render_injection_content())

    def _ensure_injection_toggle(self) -> None:
        """Ensure injection toggle exists if we have injection content."""
        if self._has_injection_content() and not self._injection_toggle:
            # Need to mount the injection toggle into the container
            try:
                container = self.query_one("#tool-card-content", Vertical)
                injection_content = self._render_injection_content()
                self._injection_toggle = InjectionToggle(
                    content=injection_content,
                    toggle_callback=self._toggle_injection,
                    id="injection-toggle",
                )
                container.mount(self._injection_toggle)
            except Exception as e:
                from massgen.logger_config import logger

                logger.warning(f"[ToolCallCard] _ensure_injection_toggle failed: {e}")

    def compose(self) -> ComposeResult:
        """Compose the card with optional injection toggle child."""
        # Use a Vertical container to stack main content and injection toggle
        with Vertical(id="tool-card-content"):
            # Main content widget
            yield Static(self._render_main_content(), id="tool-main-content")

            # Injection toggle (if we have injection content)
            if self._has_injection_content():
                injection_content = self._render_injection_content()
                self._injection_toggle = InjectionToggle(
                    content=injection_content,
                    toggle_callback=self._toggle_injection,
                    id="injection-toggle",
                )
                yield self._injection_toggle

    def _render_main_content(self) -> Text:
        """Render the main card content (without injection)."""
        if self._is_subagent:
            return self._render_subagent()
        if self._is_terminal:
            return self._render_terminal_tool()
        return self._render_collapsed_without_injection()

    def _render_terminal_tool(self) -> Text:
        """Render terminal tool card (new_answer, vote) with hero styling.

        Terminal tools are the culmination of agent work, so we show them
        prominently with the key information (vote target, reason, answer preview).
        """
        import json
        import re

        text = Text()

        # Status icon and tool name
        status_icon = self.STATUS_ICONS.get(self._status, "◉")
        elapsed = self._get_elapsed_str()

        # Header line with category-aware styling for terminal tools
        header_color = self._category.get("color", "#ffa500")
        if self._status == "running":
            text.append("▶ ", style=f"bold {header_color}")
            text.append(self._display_name, style=f"bold {header_color}")
            text.append(" ")
            text.append(status_icon, style=header_color)
            text.append(" ...", style="dim italic")
        else:
            text.append("★ ", style=f"bold {header_color}")
            text.append(self._display_name, style=f"bold {header_color}")
            text.append(" ")
            if self._status == "success":
                text.append(status_icon, style="green")
            elif self._status == "error":
                text.append(status_icon, style="red")
            else:
                text.append(status_icon, style="dim")
            if elapsed:
                text.append(f" {elapsed}", style="dim")

        # Parse params to extract meaningful info
        voted_for = None
        reason = None
        answer_preview = None
        stop_summary = None
        stop_status = None

        # Try to get full params first, fall back to summary
        params_str = self._params_full or self._params

        if params_str:
            # First try JSON parsing
            try:
                params = json.loads(params_str)
                if isinstance(params, dict):
                    voted_for = params.get("voted_for") or params.get("vote_for")
                    reason = params.get("reason")
                    # For new_answer, try to get a preview
                    answer_preview = params.get("answer") or params.get("content")
                    # For stop tool
                    stop_summary = params.get("summary")
                    stop_status = params.get("status")
            except (json.JSONDecodeError, TypeError):
                # Not JSON - try to parse key="value" format
                # e.g., voted_for="agent_a", reason="some reason here"
                voted_for_match = re.search(r'voted_for="([^"]*)"', params_str)
                if voted_for_match:
                    voted_for = voted_for_match.group(1)

                reason_match = re.search(r'reason="([^"]*)"', params_str)
                if reason_match:
                    reason = reason_match.group(1)

                answer_match = re.search(r'answer="([^"]*)"', params_str)
                if answer_match:
                    answer_preview = answer_match.group(1)

                summary_match = re.search(r'summary="([^"]*)"', params_str)
                if summary_match:
                    stop_summary = summary_match.group(1)

                status_match = re.search(r'status="([^"]*)"', params_str)
                if status_match:
                    stop_status = status_match.group(1)

        # Display key info prominently
        tool_lower = self.tool_name.lower()

        if "stop" in tool_lower and "vote" not in tool_lower:
            # Decomposition mode stop tool
            if stop_status:
                text.append("\n  ")
                text.append("Status: ", style="dim")
                status_style = "bold green" if stop_status == "complete" else "bold yellow"
                text.append(str(stop_status), style=status_style)

            if stop_summary:
                text.append("\n  ")
                text.append("Summary: ", style="dim")
                summary_text = str(stop_summary)
                if len(summary_text) > 120:
                    summary_text = summary_text[:117] + "..."
                text.append(summary_text, style="italic #c9d1d9")
            elif params_str and not stop_status:
                text.append("\n  ")
                args_display = self._truncate_params_display(params_str, 100)
                text.append(args_display, style="dim")

        elif "vote" in tool_lower:
            if voted_for:
                text.append("\n  ")
                text.append("Voted for: ", style="dim")
                text.append(str(voted_for), style="bold green")

            if reason:
                text.append("\n  ")
                text.append("Reason: ", style="dim")
                # Wrap reason text nicely
                reason_text = str(reason)
                if len(reason_text) > 120:
                    reason_text = reason_text[:117] + "..."
                text.append(reason_text, style="italic #c9d1d9")
            elif not voted_for and params_str:
                # Fallback - show raw params if we couldn't parse anything
                text.append("\n  ")
                args_display = self._truncate_params_display(params_str, 100)
                text.append(args_display, style="dim")

        elif "new_answer" in tool_lower:
            if answer_preview:
                text.append("\n  ")
                preview = str(answer_preview).replace("\n", " ")
                if len(preview) > 100:
                    preview = preview[:97] + "..."
                text.append(preview, style="#c9d1d9")
            elif params_str:
                # Fallback to showing params
                text.append("\n  ")
                args_display = self._truncate_params_display(params_str, 100)
                text.append(args_display, style="dim")

        elif "checkpoint" in tool_lower:
            # Checkpoint hero card. Two schemas share this rendering path:
            #   internal `mcp__massgen_checkpoint__checkpoint` → task / eval_criteria / context
            #   standalone `mcp__massgen_checkpoint_standalone__checkpoint`
            #     → objective / eval_criteria / action_goals
            # Result also differs (internal: {message: ...}; standalone: {plan: [...], logs_dir: ...}).
            primary = None  # task or objective
            eval_criteria = None
            context = None
            action_goals = None

            if params_str:
                try:
                    params = json.loads(params_str)
                    if isinstance(params, dict):
                        primary = params.get("task") or params.get("objective")
                        eval_criteria = params.get("eval_criteria")
                        context = params.get("context")
                        action_goals = params.get("action_goals")
                except (json.JSONDecodeError, TypeError):
                    pass

            # Show task/objective prominently
            if primary:
                text.append("\n  ")
                primary_text = str(primary).replace("\n", " ")
                if len(primary_text) > 140:
                    primary_text = primary_text[:137] + "..."
                text.append(primary_text, style="#c9d1d9")

            # Show eval criteria as inline tag boxes
            if eval_criteria and isinstance(eval_criteria, list):
                text.append("\n  ")
                for i, criterion in enumerate(eval_criteria):
                    crit_text = str(criterion)
                    # Truncate long criteria for tag display
                    if len(crit_text) > 40:
                        crit_text = crit_text[:37] + "..."
                    text.append(f" {crit_text} ", style="on #2d2d3d #a0a0c0")
                    # Spacing between tags
                    if i < len(eval_criteria) - 1:
                        text.append(" ")

            # Standalone-only: action_goals tag count (objective mode)
            if action_goals and isinstance(action_goals, list) and not eval_criteria:
                text.append("\n  ")
                text.append(
                    f" {len(action_goals)} action goal{'s' if len(action_goals) != 1 else ''} ",
                    style="on #2d2d3d #a0a0c0",
                )

            # Show context summary if present (and no task/objective to avoid redundancy)
            if context and not primary:
                text.append("\n  ")
                ctx_text = str(context).replace("\n", " ")
                if len(ctx_text) > 100:
                    ctx_text = ctx_text[:97] + "..."
                text.append(ctx_text, style="dim italic")

            # Show result message on completion
            if self._status == "success" and self._result:
                result_msg = None
                try:
                    result_data = json.loads(self._result)
                    if isinstance(result_data, dict):
                        # Internal: {"message": "..."}; standalone: {"plan": [...], "logs_dir": "..."}.
                        result_msg = result_data.get("message")
                        if not result_msg:
                            plan = result_data.get("plan")
                            if isinstance(plan, list) and plan:
                                result_msg = f"Plan returned ({len(plan)} step{'s' if len(plan) != 1 else ''})"
                            elif result_data.get("status") == "ok":
                                result_msg = "checkpoint completed"
                except (json.JSONDecodeError, TypeError):
                    pass
                if result_msg:
                    text.append("\n  ")
                    text.append("→ ", style="dim green")
                    msg_text = str(result_msg)
                    if len(msg_text) > 120:
                        msg_text = msg_text[:117] + "..."
                    text.append(msg_text, style="dim green")

        # Show error if any
        if self._error:
            text.append("\n  ")
            text.append("✗ ", style="red")
            error_preview = self._error.replace("\n", " ")
            if len(error_preview) > 80:
                error_preview = error_preview[:77] + "..."
            text.append(error_preview, style="dim red")

        return text

    def _toggle_injection(self) -> None:
        """Toggle injection expansion (called by InjectionToggle)."""
        from massgen.logger_config import logger

        self._injection_expanded = not self._injection_expanded
        logger.info(f"[ToolCallCard] _toggle_injection: expanded={self._injection_expanded}")

        # Update CSS class for height adjustment
        if self._injection_expanded:
            self.add_class("has-injection")
        else:
            self.remove_class("has-injection")

        # Update injection toggle content and CSS class
        if self._injection_toggle:
            new_content = self._render_injection_content()
            logger.info(f"[ToolCallCard] updating toggle content, length={len(str(new_content))}")
            self._injection_toggle.update_content(new_content)
            # Add/remove expanded class for CSS height adjustment
            if self._injection_expanded:
                self._injection_toggle.add_class("expanded")
            else:
                self._injection_toggle.remove_class("expanded")
        else:
            logger.warning("[ToolCallCard] _injection_toggle is None!")

    def _render_collapsed_without_injection(self) -> Text:
        """Render card view without injection content (injection is in separate widget).

        Compact design - status inline after tool name, no fixed-width padding:
        Collapsed: `▸ filesystem/read_file ✓ 0.3s`
        Expanded:  `▾ filesystem/read_file ✓ 0.3s`
                   `  {"path": "/tmp/example.txt"}`
                   `  → File contents: Hello world...`
        """
        text = Text()

        # Low-value hooks to hide (these just add noise without useful info)
        hidden_hook_prefixes = {
            "timeout_allowed",
            "round_allowed",
            "per_round_allowed",
            "timeout_hard",
            "timeout_soft",
            "round_timeout_hard",
            "round_timeout_soft",
        }

        # Pre-hooks (shown above tool line) - only show interesting ones
        for hook in self._pre_hooks:
            hook_name = hook.get("hook_name", "unknown")
            decision = hook.get("decision", "allow")
            reason = hook.get("reason", "")

            # Skip low-value hooks that just show "allowed" (use prefix matching)
            if decision != "deny" and any(hook_name.startswith(prefix) for prefix in hidden_hook_prefixes):
                continue

            if decision == "deny":
                text.append("⊘ ", style="bold red")
                text.append(f"{hook_name}: ", style="red")
                text.append("BLOCKED", style="bold red")
                if reason:
                    reason_text = f" - {reason[:40]}..." if len(reason) > 40 else f" - {reason}"
                    text.append(reason_text + "\n", style="dim red")
                else:
                    text.append("\n")

        # Tool card content - compact single line format
        status_icon = self.STATUS_ICONS.get(self._status, "◉")
        elapsed = self._get_elapsed_str()

        # Expand/collapse indicator
        if self._status == "running":
            text.append("▶ ", style="bold cyan")
        elif self._collapsed:
            text.append("▸ ", style="dim")
        else:
            text.append("▾ ", style="dim")

        # Tool name with status-based styling
        if self._status == "running":
            text.append(self._display_name, style="bold cyan")
        elif self._status == "error":
            text.append(self._display_name, style="bold")
        else:
            text.append(self._display_name, style="bold")

        # Status icon inline (no padding - flows naturally)
        text.append(" ")
        if self._status == "success":
            text.append(status_icon, style="green")
        elif self._status == "error":
            text.append(status_icon, style="red")
        elif self._status == "running":
            text.append(status_icon, style="yellow")
        else:
            text.append(status_icon, style="dim yellow")

        # Elapsed time (compact format)
        if elapsed:
            text.append(f" {elapsed}", style="dim")
        elif self._status == "running":
            text.append(" ...", style="dim italic")

        # Inline preview when collapsed - show hint of params/result in dim text
        if self._collapsed:
            preview = self._get_inline_preview()
            if preview:
                text.append(f"  {preview}", style="dim italic #555555")

        # Expanded content - show params and result
        if not self._collapsed:
            # Args preview
            if self._params:
                text.append("\n  ")
                args_display = self._truncate_params_display(self._params, 77)
                text.append(args_display, style="dim")

            # Result or error preview - preserve newlines for readability
            if self._result:
                # Show first 2 meaningful lines of result
                lines = [ln.strip() for ln in self._result.split("\n") if ln.strip()]
                if not lines:
                    lines = [self._result.strip()[:75]]

                text.append("\n  → ", style="dim green")
                if len(lines) > 2:
                    # Show first 2 lines with continuation indicator
                    first_line = lines[0][:72] + "..." if len(lines[0]) > 75 else lines[0]
                    text.append(first_line, style="dim green")
                    second_line = lines[1][:72] + "..." if len(lines[1]) > 75 else lines[1]
                    text.append(f"\n  → {second_line}", style="dim green")
                    text.append(f"\n  (+{len(lines) - 2} more lines)", style="dim italic #6e7681")
                elif len(lines) == 2:
                    first_line = lines[0][:72] + "..." if len(lines[0]) > 75 else lines[0]
                    text.append(first_line, style="dim green")
                    second_line = lines[1][:72] + "..." if len(lines[1]) > 75 else lines[1]
                    text.append(f"\n  → {second_line}", style="dim green")
                else:
                    result_line = lines[0][:72] + "..." if len(lines[0]) > 75 else lines[0]
                    text.append(result_line, style="dim green")
            elif self._error:
                text.append("\n  ✗ ")
                error_preview = self._error.replace("\n", " ")
                if len(error_preview) > 75:
                    error_preview = error_preview[:72] + "..."
                text.append(error_preview, style="dim red")

        return text

    def _render_injection_content(self) -> Text:
        """Render the injection content for the InjectionToggle widget.

        Returns:
            Rich Text with injection preview (collapsed) or full content (expanded).
        """
        from massgen.logger_config import logger

        text = Text()
        logger.info(
            f"[ToolCallCard] _render_injection_content: expanded={self._injection_expanded}, " f"num_hooks={len(self._post_hooks)}",
        )

        for hook in self._post_hooks:
            injection_content = hook.get("injection_content")
            if injection_content:
                logger.info(
                    f"[ToolCallCard] rendering injection: hook={hook.get('hook_name')}, " f"content_len={len(injection_content)}",
                )
                # Generate clean preview without decorative lines
                preview = self._generate_injection_preview(injection_content)

                if self._injection_expanded:
                    # Expanded view - show full content
                    text.append("  ▼ ", style="dim")
                    text.append("📥 ", style="bold #d2a8ff")
                    text.append(hook.get("hook_name", "injection"), style="bold #d2a8ff")
                    text.append(" (click to collapse)", style="dim italic")
                    execution_time = hook.get("execution_time_ms")
                    if execution_time:
                        text.append(f" ({execution_time:.1f}ms)", style="dim")
                    text.append("\n")

                    # Render content lines (limit to prevent huge displays)
                    max_lines = 20
                    content_lines = injection_content.split("\n")
                    for i, line in enumerate(content_lines[:max_lines]):
                        text.append("    ", style="dim")
                        text.append(line, style="#c9b8e0")
                        if i < min(len(content_lines), max_lines) - 1:
                            text.append("\n")

                    if len(content_lines) > max_lines:
                        text.append("\n")
                        text.append(f"    ... ({len(content_lines) - max_lines} more lines)", style="dim italic")
                else:
                    # Collapsed view - show arrow and preview with hint
                    text.append("  ▶ ", style="dim")
                    text.append("📥 ", style="bold #d2a8ff")
                    text.append(hook.get("hook_name", "injection"), style="bold #d2a8ff")
                    text.append(": ", style="dim")
                    text.append(preview, style="#c9b8e0")
                    text.append(" (click to expand)", style="dim italic")

        return text

    def _generate_injection_preview(self, content: str, max_length: int = 60) -> str:
        """Generate a clean preview from injection content."""
        # Split into lines and filter out decorative/empty lines
        lines = content.split("\n")
        meaningful_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("=") and stripped.count("=") > 10:
                continue
            if stripped.startswith("-") and stripped.count("-") > 10:
                continue
            meaningful_lines.append(stripped)

        if meaningful_lines:
            preview = " ".join(meaningful_lines)
        else:
            preview = content.replace("\n", " ").strip()

        if len(preview) > max_length:
            return preview[:max_length] + "..."
        return preview

    def _render_subagent(self) -> Text:
        """Render specialized subagent card with task bullets and workspace.

        Compact design - status inline after tool name:
        `▶ Spawn Subagents ◉ ...`
        `  • Task 1: Research competitor analysis`
        """
        text = Text()

        # Header line - compact format with inline status
        status_icon = self.STATUS_ICONS.get(self._status, "◉")
        elapsed = self._get_elapsed_str()

        # Expand/collapse indicator
        if self._status == "running":
            text.append("▶ ", style="bold #9070c0")
        elif self._expanded:
            text.append("▾ ", style="dim")
        else:
            text.append("▸ ", style="dim")

        # Tool name
        if self._status == "running":
            text.append(self._display_name, style="bold #9070c0")
        else:
            text.append(self._display_name, style="bold")

        # Status icon inline (no padding)
        text.append(" ")
        if self._status == "success":
            text.append(status_icon, style="green")
        elif self._status == "error":
            text.append(status_icon, style="red")
        elif self._status == "running":
            text.append(status_icon, style="#9070c0")
        else:
            text.append(status_icon, style="dim #9070c0")

        # Elapsed time
        if elapsed:
            text.append(f" {elapsed}", style="dim")
        elif self._status == "running":
            text.append(" ...", style="dim italic")

        # Compact mode: utility tools with no tasks/workspace stay on one line.
        # Spawn tools with tasks or workspace use multi-line layout.
        is_compact = not self._subagent_tasks and not self._workspace_content

        # Render bullet list of subagent tasks
        if self._subagent_tasks:
            for i, task in enumerate(self._subagent_tasks):
                task_desc = task.get("description", task.get("prompt", f"Task {i + 1}"))
                task_status = task.get("status", "pending")

                # Status indicator for each task
                if task_status == "running":
                    bullet = "◉"
                    style = "bold #9070c0"
                elif task_status == "completed":
                    bullet = "✓"
                    style = "green"
                elif task_status == "error":
                    bullet = "✗"
                    style = "red"
                else:
                    bullet = "○"
                    style = "dim"

                text.append(f"\n  {bullet} ", style=style)
                # Truncate long descriptions
                if len(task_desc) > 60:
                    task_desc = task_desc[:57] + "..."
                text.append(task_desc, style="dim" if task_status == "pending" else style)
        elif self._params and self._params.strip() not in ("{}", "{ }"):
            # Fallback: show params if non-trivial and no parsed tasks
            if is_compact:
                text.append("  ")
            else:
                text.append("\n  ")
            args_display = self._truncate_params_display(self._params, 67)
            text.append(args_display, style="dim")

        # Expanded workspace content
        if self._expanded:
            content = self._workspace_content or self._get_formatted_result()
            if content:
                text.append("\n  ─────────────────────────────────────\n", style="dim #9070c0")
                lines = content.split("\n")[:15]
                for line in lines:
                    if len(line) > 70:
                        line = line[:67] + "..."
                    text.append(f"  {line}\n", style="dim")
                if len(content.split("\n")) > 15:
                    text.append("  ...(more)...\n", style="dim italic")
        elif not self._expanded and not is_compact and (self._workspace_content or self._result):
            # Multi-line tools: expand hint on its own line
            text.append("\n  ", style="dim")
            text.append("[click to expand]", style="dim italic #9070c0")

        # Result/error summary (when completed and not expanded)
        if self._result and not self._expanded:
            # Compact tools: result preview inline on header line
            # Multi-line tools: result preview on its own line
            text.append("  → " if is_compact else "\n  → ")
            result_preview = self._result.replace("\n", " ")
            max_len = 80 if is_compact else 55
            if len(result_preview) > max_len:
                result_preview = result_preview[: max_len - 3] + "..."
            text.append(result_preview, style="dim green")
        elif self._error:
            text.append("  ✗ " if is_compact else "\n  ✗ ")
            error_preview = self._error.replace("\n", " ")
            if len(error_preview) > 55:
                error_preview = error_preview[:52] + "..."
            text.append(error_preview, style="dim red")

        return text

    def _get_elapsed_str(self) -> str:
        """Get elapsed time as formatted string."""
        end = self._end_time or datetime.now()
        elapsed = (end - self._start_time).total_seconds()

        if elapsed < 60:
            return f"({elapsed:.1f}s)"
        else:
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            return f"({mins}m{secs}s)"

    def _get_available_preview_width(self) -> int:
        """Calculate available width for inline preview based on terminal size."""
        try:
            if self.app and hasattr(self.app, "size"):
                terminal_width = self.app.size.width
                # Subtract: indicator(2) + name(~25) + status(1) + time(~8) + spacing(5)
                used_width = len(self._display_name) + 20
                available = terminal_width - used_width
                return max(30, min(available, 200))  # Between 30 and 200 chars
        except Exception:
            pass
        return 60  # Default

    def _shorten_path(self, path: str, max_len: int) -> str:
        """Shorten a path, keeping the end (filename/dirs) visible.

        For long absolute paths, shows .../<meaningful_part> instead of
        /very/long/path/that/gets/trun...
        """
        if len(path) <= max_len:
            return path

        # For paths, keep the end (filename + parent dirs) visible
        if "/" in path or "\\" in path:
            # Reserve 3 chars for "..."
            suffix_len = max_len - 3
            if suffix_len > 0:
                return "..." + path[-suffix_len:]

        # Fallback: truncate from the end (non-path values)
        return path[: max_len - 3] + "..."

    def _is_path_like(self, key: str, value: str) -> bool:
        """Check if a key/value pair looks like a file path."""
        # Key-based detection
        if key in ("path", "file_path", "directory", "dir", "folder"):
            return True
        # Value-based detection
        if value.startswith("/") or value.startswith("~"):
            return True
        if len(value) > 3 and value[1:3] == ":\\":  # Windows paths like C:\
            return True
        return False

    def _truncate_params_display(self, params_str: str, max_len: int) -> str:
        """Truncate params string with path-aware shortening.

        For JSON params containing paths, shortens the path values to show
        the meaningful end (filename/dirs) instead of truncating from end.
        """
        import json
        import re

        if len(params_str) <= max_len:
            return params_str

        # Try to parse as JSON and shorten path values
        try:
            params = json.loads(params_str)
            if isinstance(params, dict):
                shortened = {}
                for key, val in params.items():
                    if isinstance(val, str) and self._is_path_like(key, val):
                        # Calculate available length per value (rough estimate)
                        val_max = max(25, max_len // 3)
                        shortened[key] = self._shorten_path(val, val_max)
                    else:
                        shortened[key] = val

                result = json.dumps(shortened)
                if len(result) <= max_len:
                    return result
                # Still too long, truncate but we've at least shortened paths
                return result[: max_len - 3] + "..."
        except (json.JSONDecodeError, TypeError):
            pass

        # Fallback: simple truncation with regex path detection
        # Try to find and shorten any long paths in the string
        path_pattern = r'"(/[^"]{40,})"'

        def shorten_match(m):
            path = m.group(1)
            shortened = self._shorten_path(path, 35)
            return f'"{shortened}"'

        result = re.sub(path_pattern, shorten_match, params_str)
        if len(result) <= max_len:
            return result

        return result[: max_len - 3] + "..."

    def _get_inline_preview(self, max_len: int = 0) -> str:
        """Get inline preview of params or result for collapsed view.

        Auto-sizes based on available terminal width if max_len not specified.
        """
        import json

        if max_len == 0:
            max_len = self._get_available_preview_width()

        preview_parts = []

        # Try to extract meaningful info from params
        if self._params:
            try:
                params = json.loads(self._params)
                if isinstance(params, dict):
                    # Prioritize certain keys for preview, show multiple if space allows
                    shown_keys = []
                    for key in ["path", "file_path", "url", "query", "command", "content"]:
                        if key in params:
                            val = str(params[key])
                            # Truncate value based on available space
                            val_max = min(len(val), max(20, max_len // 2))
                            if len(val) > val_max:
                                # Use path-aware shortening for path-like values
                                if self._is_path_like(key, val):
                                    val = self._shorten_path(val, val_max)
                                else:
                                    val = val[: val_max - 3] + "..."
                            shown_keys.append(f"{key}={val}")
                            if len(" ".join(shown_keys)) > max_len - 20:
                                break  # Stop if we've used most of the space
                    preview_parts.extend(shown_keys)
            except (json.JSONDecodeError, TypeError):
                # Not JSON, show truncated raw params
                raw = self._params.replace("\n", " ").strip()
                raw_max = min(len(raw), max_len - 10)
                if len(raw) > raw_max:
                    raw = raw[: raw_max - 3] + "..."
                if raw:
                    preview_parts.append(raw)

        # Add result hint if completed and space allows
        if self._result and self._status == "success":
            current_len = len(" ".join(preview_parts))
            remaining = max_len - current_len - 5
            if remaining > 15:
                result_hint = self._result.replace("\n", " ").strip()
                if len(result_hint) > remaining:
                    result_hint = result_hint[: remaining - 3] + "..."
                if result_hint:
                    preview_parts.append(f"→ {result_hint}")
        elif self._error and self._status == "error":
            current_len = len(" ".join(preview_parts))
            remaining = max_len - current_len - 5
            if remaining > 15:
                error_hint = self._error.replace("\n", " ").strip()
                if len(error_hint) > remaining:
                    error_hint = error_hint[: remaining - 3] + "..."
                if error_hint:
                    preview_parts.append(f"✗ {error_hint}")

        result = " ".join(preview_parts)
        if len(result) > max_len:
            result = result[: max_len - 3] + "..."
        return result

    def on_click(self, event: Click) -> None:
        """Handle click - context-aware behavior.

        - Click on left edge (x < 3): collapse if expanded
        - Click when collapsed: expand
        - Click when expanded (not on left edge): open detail modal
        - Terminal tools (new_answer, vote) cannot be collapsed
        - Subagent tools: same as above (expand → modal on second click)

        Note: Injection content expansion is handled by the InjectionToggle widget,
        which intercepts clicks on the injection area.
        """
        if self._is_subagent:
            click_x = event.x if hasattr(event, "x") else 0
            on_left_edge = click_x < 3
            if not self._expanded or on_left_edge:
                self.toggle_expanded()
            else:
                # Expanded + click elsewhere -> open detail modal (like regular tools)
                self.post_message(self.ToolCardClicked(self))
            return

        # Terminal tools always stay expanded - clicking opens detail modal
        if self._is_terminal:
            self.post_message(self.ToolCardClicked(self))
            return

        # Check if click is on the left edge (collapse zone)
        click_x = event.x if hasattr(event, "x") else 0
        on_left_edge = click_x < 3

        if self._collapsed:
            # Collapsed -> expand on any click
            self._collapsed = False
            self.remove_class("collapsed")
            self.add_class("expanded")
            self._refresh_main_content()
        elif on_left_edge:
            # Expanded + click on left edge -> collapse
            self._collapsed = True
            self.add_class("collapsed")
            self.remove_class("expanded")
            self._refresh_main_content()
        else:
            # Expanded + click elsewhere -> open detail modal
            self.post_message(self.ToolCardClicked(self))

    def _has_injection_content(self) -> bool:
        """Check if any post-hook has injection content."""
        for hook in self._post_hooks:
            if hook.get("injection_content"):
                return True
        return False

    def set_params(self, params: str, params_full: str | None = None) -> None:
        """Set the tool parameters.

        Args:
            params: Truncated parameters for card display.
            params_full: Full parameters for modal (if different from params).
        """
        self._params = params
        self._params_full = params_full if params_full else params
        self._refresh_main_content()

    def set_result(self, result: str, result_full: str | None = None) -> None:
        """Set successful result.

        Args:
            result: Truncated result for card display.
            result_full: Full result for modal (if different from result).
        """
        self._status = "success"
        self._result = result
        self._result_full = result_full if result_full else result
        self._end_time = datetime.now()
        self._stop_elapsed_timer()  # Stop the timer now that tool is complete
        self.remove_class("status-running")
        self.add_class("status-success")
        self._refresh_main_content()

    def set_error(self, error: str) -> None:
        """Set error result.

        Args:
            error: Error message to display.
        """
        self._status = "error"
        self._error = error
        self._end_time = datetime.now()
        self._stop_elapsed_timer()  # Stop the timer now that tool is complete
        self.remove_class("status-running")
        self.add_class("status-error")
        self._refresh_main_content()

    def set_background_result(
        self,
        result: str,
        result_full: str | None = None,
        async_id: str | None = None,
    ) -> None:
        """Set result for a background/async operation.

        Unlike set_result(), this keeps the timer running since the operation
        continues in the background. Use this for operations like background shells
        that return immediately but continue executing.

        Args:
            result: Truncated result for card display (e.g., "Started: shell_abc123").
            result_full: Full result for modal.
            async_id: Optional identifier for the async operation (e.g., shell_id).
        """
        self._status = "background"
        self._result = result
        self._result_full = result_full if result_full else result
        self._async_id = async_id
        self._is_background = True
        # NOTE: We do NOT stop the timer - background operations are still running
        # NOTE: We do NOT set _end_time - operation is ongoing
        self.remove_class("status-running")
        self.add_class("status-background")
        self._refresh_main_content()

    def add_pre_hook(
        self,
        hook_name: str,
        decision: str,
        reason: str | None = None,
        execution_time_ms: float | None = None,
        injection_content: str | None = None,
    ) -> None:
        """Add a pre-tool hook execution to display.

        Args:
            hook_name: Name of the hook
            decision: "allow", "deny", or "error"
            reason: Reason for the decision (if any)
            execution_time_ms: How long the hook took
            injection_content: Full injection content (if any)
        """
        self._pre_hooks.append(
            {
                "hook_name": hook_name,
                "decision": decision,
                "reason": reason,
                "execution_time_ms": execution_time_ms,
                "injection_content": injection_content,
                "timestamp": datetime.now(),
            },
        )
        self._refresh_main_content()

    def add_post_hook(
        self,
        hook_name: str,
        injection_preview: str | None = None,
        execution_time_ms: float | None = None,
        injection_content: str | None = None,
    ) -> None:
        """Add a post-tool hook execution to display.

        Args:
            hook_name: Name of the hook
            injection_preview: Preview of injected content (if any)
            execution_time_ms: How long the hook took
            injection_content: Full injection content (if any)
        """
        from massgen.logger_config import logger

        logger.info(
            f"[ToolCallCard] add_post_hook: tool={self.tool_name}, hook={hook_name}, " f"has_content={bool(injection_content)}, is_mounted={self.is_mounted}",
        )
        self._post_hooks.append(
            {
                "hook_name": hook_name,
                "injection_preview": injection_preview,
                "injection_content": injection_content,
                "execution_time_ms": execution_time_ms,
                "timestamp": datetime.now(),
            },
        )
        self._refresh_main_content()

        # If this hook has injection content, ensure the toggle widget exists
        if injection_content:
            self._ensure_injection_toggle()
            self._refresh_injection_toggle()

    # === Subagent-specific methods ===

    def set_subagent_tasks(self, tasks: list[dict]) -> None:
        """Set the list of subagent tasks for display.

        Args:
            tasks: List of task dicts with keys:
                - description or prompt: Task description text
                - status: "pending", "running", "completed", or "error"
                - agent_id: Optional agent identifier
        """
        self._subagent_tasks = tasks
        self._refresh_main_content()

    def update_subagent_task_status(self, task_index: int, status: str) -> None:
        """Update the status of a specific subagent task.

        Args:
            task_index: Index of the task to update
            status: New status ("pending", "running", "completed", "error")
        """
        if 0 <= task_index < len(self._subagent_tasks):
            self._subagent_tasks[task_index]["status"] = status
            self._refresh_main_content()

    def _get_formatted_result(self) -> str | None:
        """Get a formatted version of the result, parsing JSON if applicable.

        For subagent tools, this extracts meaningful information from the JSON result.
        For broadcast/ask_others tools, this formats responses nicely.
        """
        if not self._result:
            return None

        import json

        try:
            data = json.loads(self._result)
            if isinstance(data, dict):
                lines = []

                # Check for broadcast/ask_others responses first
                if "responses" in data and isinstance(data.get("responses"), list):
                    # Format broadcast responses nicely
                    status = data.get("status", "unknown")
                    lines.append(f"Status: {status}")

                    responses = data["responses"]
                    if responses:
                        lines.append("")
                        for resp in responses:
                            responder = resp.get("responder_id", "unknown")
                            content = resp.get("content", "")
                            is_human = resp.get("is_human", False)

                            if is_human:
                                lines.append("👤 Human response:")
                            else:
                                lines.append(f"🤖 {responder}:")

                            # Show response content with some formatting
                            content_lines = content.strip().split("\n")
                            for cl in content_lines[:10]:  # Limit lines
                                if len(cl) > 80:
                                    cl = cl[:77] + "..."
                                lines.append(f"   {cl}")
                            if len(content_lines) > 10:
                                lines.append(f"   ... ({len(content_lines) - 10} more lines)")
                            lines.append("")
                    else:
                        lines.append("No responses received.")

                    # Show Q&A history if present
                    qa_history = data.get("human_qa_history", [])
                    if qa_history:
                        lines.append("─" * 40)
                        lines.append("Previous Q&A this session:")
                        for qa in qa_history[-3:]:  # Last 3
                            q = qa.get("question", "")[:50]
                            a = qa.get("answer", "")[:50]
                            lines.append(f"  Q: {q}...")
                            lines.append(f"  A: {a}...")

                    return "\n".join(lines)

                # Format subagent-specific results nicely
                if "subagent_id" in data:
                    lines.append(f"Subagent: {data['subagent_id']}")
                if "status" in data:
                    lines.append(f"Status: {data['status']}")
                if "message" in data:
                    lines.append(f"Message: {data['message']}")
                if "result" in data:
                    result = data["result"]
                    if isinstance(result, str):
                        lines.append(f"Result: {result[:200]}")
                    elif isinstance(result, dict):
                        lines.append("Result:")
                        for k, v in list(result.items())[:5]:
                            v_str = str(v)[:60]
                            lines.append(f"  {k}: {v_str}")
                if "error" in data:
                    lines.append(f"Error: {data['error']}")
                if "spawned_subagents" in data:
                    lines.append("Spawned Subagents:")
                    for sa in data["spawned_subagents"][:5]:
                        sa_id = sa.get("id", sa.get("subagent_id", "unknown"))
                        sa_prompt = sa.get("prompt", sa.get("task", ""))[:50]
                        lines.append(f"  • {sa_id}: {sa_prompt}")

                if lines:
                    return "\n".join(lines)

                # Fallback: pretty print JSON
                return json.dumps(data, indent=2)[:500]
        except (json.JSONDecodeError, TypeError):
            pass

        # Return raw result if not JSON
        return self._result[:500] if self._result else None

    def set_workspace_content(self, content: str) -> None:
        """Set the workspace content for expanded view.

        Args:
            content: The workspace/output content to display when expanded.
        """
        self._workspace_content = content
        self._refresh_main_content()

    def toggle_expanded(self) -> None:
        """Toggle the expanded state of the subagent card."""
        self._expanded = not self._expanded
        if self._expanded:
            self.add_class("expanded")
        else:
            self.remove_class("expanded")
        self._refresh_main_content()

    @property
    def is_expanded(self) -> bool:
        """Check if the subagent card is expanded."""
        return self._expanded

    @property
    def subagent_tasks(self) -> list[dict]:
        """Get the list of subagent tasks."""
        return self._subagent_tasks

    @property
    def workspace_content(self) -> str | None:
        """Get the workspace content."""
        return self._workspace_content

    @property
    def pre_hooks(self) -> list:
        """Get list of pre-hooks for modal display."""
        return self._pre_hooks

    @property
    def post_hooks(self) -> list:
        """Get list of post-hooks for modal display."""
        return self._post_hooks

    @property
    def status(self) -> str:
        """Get current status."""
        return self._status

    @property
    def display_name(self) -> str:
        """Get display name."""
        return self._display_name

    @property
    def icon(self) -> str:
        """Get category icon (deprecated - returns empty string)."""
        return ""

    @property
    def params(self) -> str | None:
        """Get full parameters string for modal."""
        return self._params_full or self._params

    @property
    def result(self) -> str | None:
        """Get full result string for modal."""
        return self._result_full or self._result

    @property
    def error(self) -> str | None:
        """Get error message."""
        return self._error

    @property
    def elapsed_str(self) -> str:
        """Get elapsed time string for modal."""
        return self._get_elapsed_str()

    @property
    def is_terminal(self) -> bool:
        """Check if this is a terminal coordination tool (new_answer, vote)."""
        return self._is_terminal
