"""
Agent Status Ribbon Widget for MassGen TUI.

Displays real-time status bar below tabs with view dropdown (rounds + final answer),
activity indicator, timeout display, tasks progress, and token/cost tracking.
"""

import logging
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, Static

logger = logging.getLogger(__name__)


class ViewSelected(Message):
    """Message emitted when a view is selected from the dropdown.

    Supports both round views and the final answer view.
    """

    def __init__(
        self,
        view_type: str,
        agent_id: str,
        round_number: int | None = None,
    ) -> None:
        """Initialize ViewSelected message.

        Args:
            view_type: Either "round" or "final_answer"
            agent_id: The agent ID this view is for
            round_number: Round number (only for view_type="round")
        """
        self.view_type = view_type
        self.agent_id = agent_id
        self.round_number = round_number
        super().__init__()


class RoundSelected(Message):
    """Message emitted when a round is selected from the dropdown.

    Legacy message - use ViewSelected instead for new code.
    """

    def __init__(self, round_number: int, agent_id: str) -> None:
        self.round_number = round_number
        self.agent_id = agent_id
        super().__init__()


class ContextPathsClicked(Message):
    """Message emitted when context paths icon is clicked."""


class ContextPathsLabel(Label):
    """Clickable context paths icon that emits ContextPathsClicked when clicked."""

    can_focus = True

    async def on_click(self) -> None:
        """Handle click on context paths label."""
        self.post_message(ContextPathsClicked())


class TasksClicked(Message):
    """Message emitted when tasks section is clicked."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__()


class TasksLabel(Label):
    """Clickable tasks label that emits TasksClicked when clicked."""

    can_focus = True

    def __init__(self, agent_id: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._agent_id = agent_id

    def set_agent_id(self, agent_id: str) -> None:
        """Update the agent ID."""
        self._agent_id = agent_id

    async def on_click(self) -> None:
        """Handle click on tasks label."""
        self.post_message(TasksClicked(self._agent_id))


class BackgroundTasksClicked(Message):
    """Message emitted when background tasks section is clicked."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__()


class BackgroundTasksLabel(Label):
    """Clickable background tasks label that emits BackgroundTasksClicked."""

    can_focus = True

    def __init__(self, agent_id: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._agent_id = agent_id

    def set_agent_id(self, agent_id: str) -> None:
        """Update the agent ID."""
        self._agent_id = agent_id

    async def on_click(self) -> None:
        """Handle click on background tasks label."""
        self.post_message(BackgroundTasksClicked(self._agent_id))


class AnswerNowClicked(Message):
    """Message emitted when the ribbon Answer Now control is clicked."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__()


class AnswerNowLabel(Label):
    """Clickable Answer Now label for the active agent."""

    can_focus = True

    def __init__(self, agent_id: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._agent_id = agent_id

    def set_agent_id(self, agent_id: str) -> None:
        """Update the agent ID."""
        self._agent_id = agent_id

    async def on_click(self) -> None:
        """Handle click on Answer Now."""
        self.post_message(AnswerNowClicked(self._agent_id))


class DropdownItem(Label):
    """Clickable dropdown item that emits its ID when clicked."""

    can_focus = True

    class Selected(Message):
        """Emitted when item is selected."""

        def __init__(self, item_id: str) -> None:
            self.item_id = item_id
            super().__init__()

    async def on_click(self) -> None:
        """Handle click."""
        self.post_message(self.Selected(self.id or ""))


class ViewDropdown(Vertical):
    """Popup dropdown menu for selecting round or final answer views.

    Design:
    ```
    ┌────────────────────────────────┐
    │ ✓ Final Answer                 │  (only if consensus reached)
    │ ─────────────────────────────  │
    │ ◉ Round 2 (current)            │
    │   Round 1                      │
    │ ↻ Round 1 (context reset)      │
    └────────────────────────────────┘
    ```
    """

    DEFAULT_CSS = """
    ViewDropdown {
        layer: overlay;
        width: auto;
        min-width: 28;
        height: auto;
        max-height: 15;
        background: $surface;
        border: solid $primary-darken-2;
        padding: 0;
        margin: 0;
        offset: 0 1;
    }

    ViewDropdown .dropdown-item {
        width: 100%;
        height: auto;
        padding: 0 1;
        background: transparent;
    }

    ViewDropdown .dropdown-item:hover {
        background: $primary-darken-3;
    }

    ViewDropdown .dropdown-item.current {
        color: $accent;
    }

    ViewDropdown .dropdown-item.final-answer {
        color: $success;
        text-style: bold;
    }

    ViewDropdown .dropdown-item.final-answer.current {
        color: $success-lighten-1;
    }

    ViewDropdown .dropdown-separator {
        width: 100%;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }

    ViewDropdown .context-reset {
        color: $warning;
    }
    """

    def __init__(
        self,
        agent_id: str,
        rounds: list[tuple[int, bool]],
        current_round: int,
        viewed_round: int | None,
        has_final_answer: bool = False,
        viewing_final_answer: bool = False,
        **kwargs,
    ) -> None:
        """Initialize the dropdown.

        Args:
            agent_id: The agent ID
            rounds: List of (round_number, is_context_reset) tuples
            current_round: The current/latest round number
            viewed_round: The round being viewed (may differ from current)
            has_final_answer: Whether final answer is available
            viewing_final_answer: Whether currently viewing final answer
        """
        super().__init__(**kwargs)
        self.agent_id = agent_id
        self._rounds = rounds
        self._current_round = current_round
        self._viewed_round = viewed_round if viewed_round is not None else current_round
        self._has_final_answer = has_final_answer
        self._viewing_final_answer = viewing_final_answer

    def compose(self) -> ComposeResult:
        """Build the dropdown items."""
        logger.info(
            f"ViewDropdown.compose: rounds={self._rounds}, has_final={self._has_final_answer}",
        )
        # Final Answer option at top (only if available)
        if self._has_final_answer:
            classes = "dropdown-item final-answer"
            if self._viewing_final_answer:
                classes += " current"
            yield DropdownItem("✓ Final Answer", classes=classes, id="view_final_answer")
            yield Static("─" * 26, classes="dropdown-separator")

        # Round options (newest first)
        sorted_rounds = sorted(self._rounds, key=lambda x: x[0], reverse=True)
        for round_num, is_context_reset in sorted_rounds:
            is_current = round_num == self._current_round
            is_viewed = round_num == self._viewed_round and not self._viewing_final_answer

            # Build label text
            if is_viewed:
                indicator = "◉"  # Currently viewed
            elif is_context_reset:
                indicator = "↻"  # Context reset
            else:
                indicator = " "

            suffix = " (current)" if is_current else ""
            if is_context_reset and not is_viewed:
                suffix = " (reset)" if not suffix else suffix + ", reset"

            label_text = f"{indicator} Round {round_num}{suffix}"

            classes = "dropdown-item"
            if is_viewed:
                classes += " current"
            if is_context_reset:
                classes += " context-reset"

            logger.info(f"ViewDropdown.compose: creating DropdownItem id=view_round_{round_num}")
            yield DropdownItem(label_text, classes=classes, id=f"view_round_{round_num}")

    def on_dropdown_item_selected(self, event: DropdownItem.Selected) -> None:
        """Handle dropdown item selection."""
        event.stop()
        item_id = event.item_id

        if item_id == "view_final_answer":
            self.post_message(ViewSelected("final_answer", self.agent_id))
            self.remove()
        elif item_id and item_id.startswith("view_round_"):
            try:
                round_num = int(item_id.replace("view_round_", ""))
                self.post_message(ViewSelected("round", self.agent_id, round_num))
                self.remove()
            except ValueError:
                pass

    def on_blur(self, event) -> None:
        """Close dropdown when focus is lost."""
        logger.info("ViewDropdown.on_blur: removing dropdown")
        self.remove()


class RoundSelector(Label):
    """Clickable round selector label that emits RoundSelectorClicked message."""

    can_focus = True

    class Clicked(Message):
        """Emitted when the round selector is clicked."""

    async def on_click(self) -> None:
        """Handle click on the round selector."""
        self.post_message(self.Clicked())


class AgentStatusRibbon(Widget):
    """Real-time status bar below tabs with bookmark-style round navigation.

    Design:
    ```
    ┌──────────────────────────────────────────────────────────────────────────┐
    │ ◀ [1] [2] [3] [✓]                              ⏱ 5:30 │ 2.4k │ $0.003   │
    └──────────────────────────────────────────────────────────────────────────┘
    ```

    Left side: Round pills (fixed width, shows last N rounds + final)
    Right side: Timeout, tokens, cost (anchored right)
    """

    # How many recent rounds to show (excluding final)
    MAX_VISIBLE_ROUNDS = 5

    DEFAULT_CSS = """
    AgentStatusRibbon {
        width: 100%;
        height: auto;
        min-height: 1;
        background: transparent;
        border-top: solid $primary-darken-3;
        padding: 0 1;
    }

    AgentStatusRibbon .ribbon-container {
        width: 100%;
        height: auto;
        layout: horizontal;
    }

    AgentStatusRibbon .round-nav {
        width: auto;
        height: 1;
        layout: horizontal;
    }

    AgentStatusRibbon .more-indicator {
        width: auto;
        height: 1;
        color: $text-muted;
        padding: 0;
        margin: 0;
    }

    AgentStatusRibbon .pill-sep {
        width: auto;
        height: 1;
        color: $text-muted;
        padding: 0;
        margin: 0 1;
    }

    AgentStatusRibbon .spacer {
        width: 1fr;
    }

    AgentStatusRibbon .ribbon-section {
        width: auto;
        height: auto;
        padding: 0 1;
    }

    AgentStatusRibbon .ribbon-divider {
        width: auto;
        height: auto;
        color: $text-muted;
    }

    AgentStatusRibbon #timeout_display {
        width: auto;
    }

    AgentStatusRibbon #timeout_display.warning {
        color: $warning;
    }

    AgentStatusRibbon #timeout_display.critical {
        color: $error;
    }

    AgentStatusRibbon #token_count {
        color: $text-muted;
        width: auto;
    }

    AgentStatusRibbon #cost_display {
        color: $text-muted;
        width: auto;
    }

    AgentStatusRibbon #context_paths_btn {
        color: $text-muted;
        width: auto;
    }

    AgentStatusRibbon #context_paths_btn:hover {
        color: $primary;
        text-style: underline;
    }

    AgentStatusRibbon #tasks_display {
        color: $text-muted;
        width: auto;
    }

    AgentStatusRibbon #tasks_display:hover {
        color: $primary;
        text-style: underline;
    }

    AgentStatusRibbon #tasks_display.has-tasks {
        color: $warning;
    }

    AgentStatusRibbon #tasks_display.hidden {
        display: none;
    }

    AgentStatusRibbon #tasks_divider.hidden {
        display: none;
    }

    AgentStatusRibbon #background_tasks_display {
        color: $text-muted;
        width: auto;
    }

    AgentStatusRibbon #background_tasks_display:hover {
        color: $primary;
        text-style: underline;
    }

    AgentStatusRibbon #background_tasks_display.has-background {
        color: $warning;
    }

    AgentStatusRibbon #background_tasks_display.hidden {
        display: none;
    }

    AgentStatusRibbon #background_tasks_divider.hidden {
        display: none;
    }

    AgentStatusRibbon #answer_now_btn {
        color: $warning;
        width: auto;
    }

    AgentStatusRibbon #answer_now_btn:hover {
        color: $primary;
        text-style: underline;
    }

    AgentStatusRibbon #answer_now_btn.wrapping-up {
        color: $warning;
    }

    AgentStatusRibbon #answer_now_btn.blocked {
        color: $error;
    }

    AgentStatusRibbon #answer_now_btn.hidden {
        display: none;
    }

    AgentStatusRibbon #answer_now_divider.hidden {
        display: none;
    }
    """

    # Reactive attributes
    current_agent: reactive[str] = reactive("")
    activity_status: reactive[str] = reactive("idle")
    elapsed_seconds: reactive[int] = reactive(0)

    # Activity status icons
    ACTIVITY_ICONS = {
        "streaming": "◉",
        "thinking": "⏳",
        "idle": "○",
        "canceled": "⏹",
        "error": "✗",
    }

    ACTIVITY_LABELS = {
        "streaming": "Streaming...",
        "thinking": "Thinking...",
        "idle": "Idle",
        "canceled": "Canceled",
        "error": "Error",
    }

    def __init__(
        self,
        agent_id: str = "",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.current_agent = agent_id
        self._rounds: dict[str, list[tuple[int, bool]]] = {}  # agent_id -> [(round_num, is_context_reset)]
        self._current_round: dict[str, int] = {}  # agent_id -> current round (live)
        self._viewed_round: dict[str, int] = {}  # agent_id -> round being viewed
        self._tasks_complete: dict[str, int] = {}
        self._tasks_total: dict[str, int] = {}
        self._background_jobs: dict[str, int] = {}
        self._tokens: dict[str, int] = {}
        self._cost: dict[str, float] = {}
        self._timeout_remaining: dict[str, int | None] = {}
        self._timeout_state: dict[str, dict[str, Any]] = {}  # agent_id -> full timeout state from orchestrator
        self._start_time: float | None = None
        self._timer_handle = None
        self._agent_start_times: dict[str, float] = {}  # agent_id -> start timestamp for total elapsed time
        self._round_start_times: dict[str, float] = {}  # agent_id -> start timestamp for current round
        self._frozen_round_elapsed: dict[str, int] = {}  # agent_id -> frozen elapsed seconds (when stopped)

        # View state tracking
        self._has_final_answer: dict[str, bool] = {}  # agent_id -> has final answer
        self._viewing_final_answer: dict[str, bool] = {}  # agent_id -> viewing final answer
        self._final_presentation_rounds: dict[str, set[int]] = {}  # agent_id -> set of final presentation round numbers
        self._dropdown_open = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="ribbon-container"):
            # Left: Round navigation (clickable to open dropdown)
            yield RoundSelector("R1", id="round_nav_label", classes="ribbon-section")
            # Spacer
            yield Static("", classes="spacer")
            # Right: Stats (anchored right)
            yield ContextPathsLabel("📂", id="context_paths_btn", classes="ribbon-section")
            yield Static("·", classes="ribbon-divider", id="context_divider")
            yield TasksLabel(agent_id=self.current_agent, id="tasks_display", classes="ribbon-section")
            yield Static("·", classes="ribbon-divider", id="tasks_divider")
            yield BackgroundTasksLabel(agent_id=self.current_agent, id="background_tasks_display", classes="ribbon-section hidden")
            yield Static("·", classes="ribbon-divider hidden", id="background_tasks_divider")
            yield AnswerNowLabel(agent_id=self.current_agent, id="answer_now_btn", classes="ribbon-section hidden")
            yield Static("·", classes="ribbon-divider hidden", id="answer_now_divider")
            yield Label("⏱ --:--", id="timeout_display", classes="ribbon-section")
            yield Static("·", classes="ribbon-divider")
            yield Label("-", id="token_count", classes="ribbon-section")
            yield Static("·", classes="ribbon-divider")
            yield Label("$--.---", id="cost_display", classes="ribbon-section")

    def on_mount(self) -> None:
        """Start the elapsed time timer and initialize display."""
        self._timer_handle = self.set_interval(1.0, self._update_elapsed_time)
        # Initialize round display with default R1
        self._update_round_display()

    def on_unmount(self) -> None:
        """Clean up timer."""
        if self._timer_handle:
            self._timer_handle.stop()

    def _update_elapsed_time(self) -> None:
        """Update the elapsed time display."""
        if self.activity_status in ("streaming", "thinking"):
            self.elapsed_seconds += 1
            self._update_activity_display()

        # Also update timeout display to refresh elapsed time
        self._update_timeout_display()

    def set_agent(self, agent_id: str) -> None:
        """Switch to displaying status for a different agent."""
        self.current_agent = agent_id
        self._refresh_all_displays()

    def reset_round_state_for_agent(self, agent_id: str) -> None:
        """Reset round tracking state for an agent at the start of a new turn."""
        from massgen.logger_config import logger

        logger.info(f"[AgentStatusRibbon] reset_round_state_for_agent() called for {agent_id}")
        logger.info(f"[AgentStatusRibbon] Before reset: _rounds={self._rounds.get(agent_id, [])}, _current_round={self._current_round.get(agent_id)}, _viewed_round={self._viewed_round.get(agent_id)}")

        # Seed with Round 1 so the ribbon shows R1 at the start of each turn
        self._rounds[agent_id] = [(1, False)]
        self._current_round[agent_id] = 1
        self._viewed_round[agent_id] = 1

        # Clear elapsed time tracking so it restarts on the new turn
        if agent_id in self._agent_start_times:
            del self._agent_start_times[agent_id]
        if agent_id in self._round_start_times:
            del self._round_start_times[agent_id]
        if agent_id in self._frozen_round_elapsed:
            del self._frozen_round_elapsed[agent_id]

        logger.info(f"[AgentStatusRibbon] After reset: _rounds={self._rounds[agent_id]}, _current_round={self._current_round[agent_id]}, _viewed_round={self._viewed_round[agent_id]}")

        # Clear final answer state
        if agent_id in self._has_final_answer:
            self._has_final_answer[agent_id] = False
        if agent_id in self._viewing_final_answer:
            self._viewing_final_answer[agent_id] = False
        if agent_id in self._final_presentation_rounds:
            self._final_presentation_rounds[agent_id].clear()

        # Update display if this is the current agent
        if agent_id == self.current_agent:
            logger.info(f"[AgentStatusRibbon] Updating round display for current agent {agent_id}")
            self._update_round_display()
            logger.info("[AgentStatusRibbon] Round display updated")

    def reset_round_state_all_agents(self) -> None:
        """Reset round tracking state for all agents at the start of a new turn."""
        for agent_id in list(self._rounds.keys()):
            self.reset_round_state_for_agent(agent_id)

    def set_activity(self, agent_id: str, status: str) -> None:
        """Set the activity status for an agent.

        Args:
            agent_id: The agent ID
            status: One of "streaming", "thinking", "idle", "canceled", "error"
        """
        if agent_id == self.current_agent:
            # Reset elapsed time when activity changes
            if status != self.activity_status:
                self.elapsed_seconds = 0
            self.activity_status = status
            self._update_activity_display()

    def _update_activity_display(self) -> None:
        """Update the activity indicator display."""
        try:
            indicator = self.query_one("#activity_indicator", Label)
            icon = self.ACTIVITY_ICONS.get(self.activity_status, "○")
            label = self.ACTIVITY_LABELS.get(self.activity_status, "Unknown")

            # Add elapsed time for active states
            if self.activity_status in ("streaming", "thinking") and self.elapsed_seconds > 0:
                text = f"{icon} {label} {self.elapsed_seconds}s"
            else:
                text = f"{icon} {label}"

            indicator.update(text)

            # Update styling
            for status_class in ("streaming", "thinking", "idle", "canceled", "error"):
                indicator.remove_class(status_class)
            indicator.add_class(self.activity_status)
        except Exception:
            pass

    def set_round(self, agent_id: str, round_number: int, is_context_reset: bool = False, is_final_presentation: bool = False) -> None:
        """Set the current round for an agent.

        Args:
            agent_id: The agent ID
            round_number: The round number
            is_context_reset: Whether this round started with a context reset
            is_final_presentation: Whether this is the final presentation round
        """
        from massgen.logger_config import logger

        logger.info(f"[AgentStatusRibbon] set_round() called: agent={agent_id}, round={round_number}, is_context_reset={is_context_reset}, is_final_presentation={is_final_presentation}")

        import time

        # Start total elapsed timer on first round for this agent
        if agent_id not in self._agent_start_times:
            self._agent_start_times[agent_id] = time.time()

        # Reset round timer on every new round (including final presentation)
        self._round_start_times[agent_id] = time.time()
        # Clear any frozen state from previous round
        if agent_id in self._frozen_round_elapsed:
            del self._frozen_round_elapsed[agent_id]

        if agent_id not in self._rounds:
            self._rounds[agent_id] = []

        # Add round if new
        existing_rounds = [r[0] for r in self._rounds[agent_id]]
        if round_number not in existing_rounds:
            logger.info(f"[AgentStatusRibbon] Adding new round {round_number} to {agent_id}")
            self._rounds[agent_id].append((round_number, is_context_reset))
        else:
            logger.info(f"[AgentStatusRibbon] Round {round_number} already exists for {agent_id}")

        # Track final presentation rounds
        if is_final_presentation:
            if agent_id not in self._final_presentation_rounds:
                self._final_presentation_rounds[agent_id] = set()
            self._final_presentation_rounds[agent_id].add(round_number)

        self._current_round[agent_id] = round_number

        # If not explicitly viewing a different round, follow the current round
        if agent_id not in self._viewed_round or self._viewed_round.get(agent_id) == round_number - 1:
            self._viewed_round[agent_id] = round_number
            # Reset final answer view when new round starts (unless explicitly staying)
            if self._viewing_final_answer.get(agent_id):
                self._viewing_final_answer[agent_id] = False

        if agent_id == self.current_agent:
            self._update_round_display()

    def set_viewed_round(self, agent_id: str, round_number: int) -> None:
        """Set which round is being viewed for an agent.

        Args:
            agent_id: The agent ID
            round_number: The round number to view
        """
        self._viewed_round[agent_id] = round_number
        self._viewing_final_answer[agent_id] = False

        if agent_id == self.current_agent:
            self._update_round_display()

    def set_final_answer_available(self, agent_id: str, available: bool = True) -> None:
        """Set whether final answer is available for an agent.

        Args:
            agent_id: The agent ID
            available: Whether final answer is now available
        """
        self._has_final_answer[agent_id] = available

        if agent_id == self.current_agent:
            self._update_round_display()

    def set_viewing_final_answer(self, agent_id: str, viewing: bool = True) -> None:
        """Set whether an agent is viewing the final answer.

        Args:
            agent_id: The agent ID
            viewing: Whether to view the final answer
        """
        self._viewing_final_answer[agent_id] = viewing

        if agent_id == self.current_agent:
            self._update_round_display()

    def get_view_state(self, agent_id: str) -> tuple[str, int | None]:
        """Get the current view state for an agent.

        Returns:
            Tuple of (view_type, round_number) where view_type is "round" or "final_answer"
        """
        if self._viewing_final_answer.get(agent_id):
            return ("final_answer", None)
        return ("round", self._viewed_round.get(agent_id, 1))

    def _update_round_display(self) -> None:
        """Update the round navigation label based on current state."""
        try:
            nav_label = self.query_one("#round_nav_label", Label)
        except Exception:
            return

        try:
            # Get round info for current agent (default to round 1)
            rounds = self._rounds.get(self.current_agent, [(1, False)])
            self._current_round.get(self.current_agent, 1)
            has_final = self._has_final_answer.get(self.current_agent, False)
            self._viewing_final_answer.get(self.current_agent, False)

            # Sort rounds and get the most recent N
            sorted_rounds = sorted(rounds, key=lambda x: x[0])
            total_rounds = len(sorted_rounds)

            # Determine which rounds to show
            if total_rounds <= self.MAX_VISIBLE_ROUNDS:
                visible_rounds = sorted_rounds
                has_more = False
            else:
                visible_rounds = sorted_rounds[-self.MAX_VISIBLE_ROUNDS :]
                has_more = True

            # Build the label text with individual underlines: "[u]R1[/u] · [u]R2[/u] · [u]✓[/u]"
            # Final presentation rounds are shown as "F" in gold/green color
            parts = []
            if has_more:
                parts.append("[u]◀[/u]")

            # Get final presentation rounds for this agent
            final_rounds = self._final_presentation_rounds.get(self.current_agent, set())

            for round_num, _ in visible_rounds:
                if round_num in final_rounds:
                    # Final presentation round - show as "F" with special gold color
                    parts.append("[bold #3fb950][u]F[/u][/bold #3fb950]")
                else:
                    parts.append(f"[u]R{round_num}[/u]")

            if has_final:
                parts.append("[u]✓[/u]")

            # Join with dots (not underlined)
            label_text = " · ".join(parts) if parts else "[u]R1[/u]"

            # Update label with Rich markup
            nav_label.update(label_text)

        except Exception:
            pass

    def set_tasks(self, agent_id: str, complete: int, total: int) -> None:
        """Set the task progress for an agent.

        Args:
            agent_id: The agent ID
            complete: Number of completed tasks
            total: Total number of tasks
        """
        self._tasks_complete[agent_id] = complete
        self._tasks_total[agent_id] = total

        if agent_id == self.current_agent:
            self._update_tasks_display()

    def _update_tasks_display(self) -> None:
        """Update the tasks progress display in ribbon."""
        try:
            tasks_label = self.query_one("#tasks_display", TasksLabel)
            tasks_divider = self.query_one("#tasks_divider", Static)

            # Update agent_id for click handling
            tasks_label.set_agent_id(self.current_agent)

            complete = self._tasks_complete.get(self.current_agent, 0)
            total = self._tasks_total.get(self.current_agent, 0)

            if total > 0:
                # Show tasks count
                tasks_label.update(f"Tasks {complete}/{total}")
                tasks_label.remove_class("hidden")
                tasks_divider.remove_class("hidden")
                if complete < total:
                    tasks_label.add_class("has-tasks")
                else:
                    tasks_label.remove_class("has-tasks")
            else:
                # Hide tasks display when no tasks
                tasks_label.update("")
                tasks_label.add_class("hidden")
                tasks_divider.add_class("hidden")
        except Exception:
            pass

    def set_background_jobs(self, agent_id: str, count: int) -> None:
        """Set the active background job count for an agent."""
        self._background_jobs[agent_id] = max(0, int(count))
        if agent_id == self.current_agent:
            self._update_background_display()

    def _update_background_display(self) -> None:
        """Update background job display in ribbon."""
        try:
            bg_label = self.query_one("#background_tasks_display", BackgroundTasksLabel)
            bg_divider = self.query_one("#background_tasks_divider", Static)

            bg_label.set_agent_id(self.current_agent)
            count = self._background_jobs.get(self.current_agent, 0)

            if count > 0:
                bg_label.update(f"BG {count}")
                bg_label.remove_class("hidden")
                bg_divider.remove_class("hidden")
                bg_label.add_class("has-background")
            else:
                bg_label.update("")
                bg_label.add_class("hidden")
                bg_divider.add_class("hidden")
                bg_label.remove_class("has-background")
        except Exception:
            pass

    def set_timeout(self, agent_id: str, remaining_seconds: int | None) -> None:
        """Set the timeout remaining for an agent (legacy, called from update_agent_timeout).

        Args:
            agent_id: The agent ID
            remaining_seconds: Seconds remaining, or None if no timeout
        """
        self._timeout_remaining[agent_id] = remaining_seconds

        if agent_id == self.current_agent:
            self._update_timeout_display()

    def stop_round_timer(self, agent_id: str) -> None:
        """Freeze the round timer at its current value.

        Called when final presentation starts or execution is cancelled.
        Stores the frozen elapsed value so the display keeps showing it.
        """
        import time

        start = self._round_start_times.get(agent_id)
        if start is not None:
            self._frozen_round_elapsed[agent_id] = int(time.time() - start)
            del self._round_start_times[agent_id]
        if agent_id == self.current_agent:
            self._update_timeout_display()

    def stop_all_round_timers(self) -> None:
        """Freeze round timers for all agents."""
        for agent_id in list(self._round_start_times.keys()):
            self.stop_round_timer(agent_id)

    def set_timeout_state(self, agent_id: str, timeout_state: dict[str, Any]) -> None:
        """Set the full timeout state for an agent.

        Args:
            agent_id: The agent ID
            timeout_state: Full timeout state dict from orchestrator containing
                elapsed, active_timeout, remaining_soft, remaining_hard,
                soft_timeout_fired, is_hard_blocked, etc.
        """
        self._timeout_state[agent_id] = timeout_state

        if agent_id == self.current_agent:
            self._update_answer_now_display()
            self._update_timeout_display()

    def _get_total_elapsed(self, agent_id: str) -> int | None:
        """Get total elapsed time in seconds since agent first started."""
        if agent_id not in self._agent_start_times:
            return None
        import time

        return int(time.time() - self._agent_start_times[agent_id])

    @staticmethod
    def _fmt_time(seconds: int) -> str:
        """Format seconds as M:SS."""
        return f"{seconds // 60}:{seconds % 60:02d}"

    def _update_timeout_display(self) -> None:
        """Update the timeout display with round timer.

        Round elapsed is recalculated from _round_start_times each tick for smooth updates.
        Total elapsed timer is shown in ExecutionStatusLine instead.

        Display format:
            Not started:              "⏱ --:--"
            No timeout, running:      "⏱ 2:15"               (round elapsed only)
            With timeout, normal:     "⏱ 2:15 / 5:00"
            With timeout, soft:       "⏱ 2:15 / 5:00 ⚠"     (yellow)
            With timeout, hard:       "⏱ 2:15 / 5:00 ✋"     (red)
        """
        try:
            import time

            timeout_label = self.query_one("#timeout_display", Label)
            now = time.time()
            timeout_label.remove_class("warning", "critical")

            # Round elapsed: use live timer if running, frozen value if stopped
            round_start = self._round_start_times.get(self.current_agent)
            frozen = self._frozen_round_elapsed.get(self.current_agent)
            if round_start is not None:
                round_elapsed = int(now - round_start)
            elif frozen is not None:
                round_elapsed = frozen
            else:
                timeout_label.update("⏱ --:--")
                return
            round_str = self._fmt_time(round_elapsed)

            # Check if timeout is configured
            ts = self._timeout_state.get(self.current_agent)
            if ts and ts.get("active_timeout"):
                limit = int(ts["active_timeout"])
                soft_fired = ts.get("soft_timeout_fired", False)
                wrap_up_requested = ts.get("wrap_up_requested", False)
                hard_blocked = ts.get("is_hard_blocked", False)
                remaining_hard = ts.get("remaining_hard")
                limit_str = self._fmt_time(limit)

                # Stage indicator
                if hard_blocked:
                    stage = " BLOCKED"
                    timeout_label.add_class("critical")
                elif soft_fired:
                    grace_text = ""
                    if remaining_hard is not None:
                        grace_text = f" {self._fmt_time(int(remaining_hard))}"
                    stage = f" Grace{grace_text}"
                    timeout_label.add_class("warning")
                elif wrap_up_requested:
                    stage = " Wrap up"
                    timeout_label.add_class("warning")
                else:
                    stage = ""

                timeout_label.update(f"⏱ {round_str} / {limit_str}{stage}")
            else:
                # No timeout configured - just show round elapsed
                timeout_label.update(f"⏱ {round_str}")
        except Exception:
            pass

    def _update_answer_now_display(self) -> None:
        """Update the ribbon Answer Now control based on timeout state."""
        try:
            answer_label = self.query_one("#answer_now_btn", AnswerNowLabel)
            answer_divider = self.query_one("#answer_now_divider", Static)
        except Exception:
            return

        answer_label.set_agent_id(self.current_agent)
        for class_name in ("hidden", "wrapping-up", "blocked"):
            answer_label.remove_class(class_name)

        ts = self._timeout_state.get(self.current_agent) or {}
        if not ts.get("active_timeout"):
            answer_label.add_class("hidden")
            answer_divider.add_class("hidden")
            return

        answer_divider.remove_class("hidden")
        hard_blocked = ts.get("is_hard_blocked", False)
        soft_fired = ts.get("soft_timeout_fired", False)
        wrap_up_requested = ts.get("wrap_up_requested", False)
        remaining_hard = ts.get("remaining_hard")

        if hard_blocked:
            answer_label.update("Blocked")
            answer_label.add_class("blocked")
            return

        if soft_fired:
            remaining_text = ""
            if remaining_hard is not None:
                remaining_text = f" {self._fmt_time(int(remaining_hard))}"
            answer_label.update(f"Wrapping up{remaining_text}")
            answer_label.add_class("wrapping-up")
            return

        if wrap_up_requested:
            answer_label.update("Wrap-up pending")
            answer_label.add_class("wrapping-up")
            return

        answer_label.update("Answer Now")

    def set_tokens(self, agent_id: str, tokens: int) -> None:
        """Set the token count for an agent.

        Args:
            agent_id: The agent ID
            tokens: Total tokens used
        """
        self._tokens[agent_id] = tokens

        if agent_id == self.current_agent:
            self._update_token_display()

    def _update_token_display(self) -> None:
        """Update the token count display."""
        try:
            token_label = self.query_one("#token_count", Label)
            tokens = self._tokens.get(self.current_agent, 0)

            if tokens >= 1000:
                token_label.update(f"{tokens / 1000:.1f}k")
            else:
                token_label.update(str(tokens) if tokens > 0 else "-")
        except Exception:
            pass

    def set_cost(self, agent_id: str, cost: float) -> None:
        """Set the cost for an agent.

        Args:
            agent_id: The agent ID
            cost: Total cost in dollars
        """
        self._cost[agent_id] = cost

        if agent_id == self.current_agent:
            self._update_cost_display()

    def _update_cost_display(self) -> None:
        """Update the cost display."""
        try:
            cost_label = self.query_one("#cost_display", Label)
            cost = self._cost.get(self.current_agent, 0.0)

            if cost > 0:
                cost_label.update(f"${cost:.3f}")
            else:
                cost_label.update("$--.---")
        except Exception:
            pass

    def _refresh_all_displays(self) -> None:
        """Refresh all displays for the current agent."""
        self._update_round_display()
        self._update_activity_display()
        self._update_answer_now_display()
        self._update_timeout_display()
        self._update_tasks_display()
        self._update_background_display()
        self._update_token_display()
        self._update_cost_display()

    def on_round_selector_clicked(self, event: RoundSelector.Clicked) -> None:
        """Handle click on the round selector - toggle dropdown."""
        event.stop()
        self._toggle_dropdown()

    def _toggle_dropdown(self) -> None:
        """Toggle the view dropdown visibility."""
        # Close any existing dropdown
        try:
            existing = self.query_one(ViewDropdown)
            existing.remove()
            self._dropdown_open = False
            return
        except Exception:
            pass

        # Create and mount new dropdown
        agent_id = self.current_agent
        rounds = self._rounds.get(agent_id, [(1, False)])
        current_round = self._current_round.get(agent_id, 1)
        viewed_round = self._viewed_round.get(agent_id, current_round)
        has_final = self._has_final_answer.get(agent_id, False)
        viewing_final = self._viewing_final_answer.get(agent_id, False)

        dropdown = ViewDropdown(
            agent_id=agent_id,
            rounds=rounds,
            current_round=current_round,
            viewed_round=viewed_round,
            has_final_answer=has_final,
            viewing_final_answer=viewing_final,
            id="view_dropdown",
        )

        self.mount(dropdown)
        logger.info("AgentStatusRibbon._toggle_dropdown: focusing dropdown")
        dropdown.focus()
        self._dropdown_open = True
        logger.info("AgentStatusRibbon._toggle_dropdown: done")

    def on_view_selected(self, event: ViewSelected) -> None:
        """Handle view selection - update local state, let event bubble."""
        self._dropdown_open = False

        if event.view_type == "final_answer":
            self._viewing_final_answer[event.agent_id] = True
        else:
            self._viewing_final_answer[event.agent_id] = False
            if event.round_number is not None:
                self._viewed_round[event.agent_id] = event.round_number

        self._update_round_display()
        # Don't stop or re-post - let the event bubble up naturally to the App
