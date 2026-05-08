"""Layer 3 Textual SVG snapshot tests for critical timeline states."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label, Static

from massgen.frontend.displays import textual_terminal_display as textual_display_module
from massgen.frontend.displays.content_handlers import ToolDisplayData
from massgen.frontend.displays.textual_terminal_display import TextualTerminalDisplay
from massgen.frontend.displays.textual_widgets.collapsible_text_card import (
    CollapsibleTextCard,
)
from massgen.frontend.displays.textual_widgets.content_sections import TimelineSection
from massgen.frontend.displays.textual_widgets.queued_input_banner import (
    QueuedInputBanner,
)
from massgen.frontend.displays.textual_widgets.subagent_card import SubagentCard
from massgen.frontend.displays.textual_widgets.tool_batch_card import (
    ToolBatchCard,
    ToolBatchItem,
)
from massgen.frontend.displays.textual_widgets.tool_card import ToolCallCard
from massgen.subagent.models import SubagentDisplayData

pytestmark = pytest.mark.snapshot


def _configure_snapshot_terminal_environment(monkeypatch) -> None:  # noqa: ANN001 - pytest fixture type
    """Pin terminal color behavior so snapshot rendering is deterministic across runners."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.setenv("COLUMNS", "140")
    monkeypatch.setenv("LINES", "42")
    monkeypatch.setenv("FORCE_COLOR", "1")


class _TimelineSnapshotApp(App):
    def compose(self) -> ComposeResult:
        yield TimelineSection(id="timeline")

    def on_mount(self) -> None:
        timeline = self.query_one(TimelineSection)
        fixed_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

        timeline.add_separator("Round 1", round_number=1)
        timeline.add_text("Agent is preparing plan", text_class="content-inline", round_number=1)

        tool_running = ToolDisplayData(
            tool_id="t1",
            tool_name="mcp__filesystem__read_text_file",
            display_name="filesystem/read_text_file",
            tool_type="mcp",
            category="filesystem",
            icon="F",
            color="blue",
            status="running",
            start_time=fixed_time,
            args_summary='{"path": "/tmp/a.txt"}',
            args_full='{"path": "/tmp/a.txt"}',
        )
        timeline.add_tool(tool_running, round_number=1)

        tool_done = ToolDisplayData(
            tool_id="t1",
            tool_name="mcp__filesystem__read_text_file",
            display_name="filesystem/read_text_file",
            tool_type="mcp",
            category="filesystem",
            icon="F",
            color="blue",
            status="success",
            start_time=fixed_time,
            end_time=fixed_time,
            args_summary='{"path": "/tmp/a.txt"}',
            args_full='{"path": "/tmp/a.txt"}',
            result_summary="read ok",
            result_full="read ok",
            elapsed_seconds=0.0,
        )
        timeline.update_tool("t1", tool_done)


async def _settle_scaffold_snapshot(pilot) -> None:  # noqa: ANN001 - fixture-provided type
    """Settle animation/timer state before capturing widget-only snapshots."""
    _complete_tool_appearance_states(pilot.app)
    _stop_all_tui_timers(pilot.app)
    await pilot.pause()


def test_timeline_snapshot_baseline(snap_compare, monkeypatch) -> None:  # noqa: ANN001 - pytest fixture type
    """Snapshot for baseline timeline state with separator, content, and tool card."""
    _configure_snapshot_terminal_environment(monkeypatch)
    assert snap_compare(
        _TimelineSnapshotApp(),
        terminal_size=(120, 32),
        run_before=_settle_scaffold_snapshot,
    )


class _TimelineBatchSnapshotApp(App):
    def compose(self) -> ComposeResult:
        yield TimelineSection(id="timeline")

    def on_mount(self) -> None:
        timeline = self.query_one(TimelineSection)
        fixed_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

        timeline.add_separator("Round 1", round_number=1)
        batch = timeline.add_batch("batch_1", "filesystem", round_number=1)
        batch._complete_appearance()

        item_one = ToolBatchItem(
            tool_id="t1",
            tool_name="mcp__filesystem__read_text_file",
            display_name="read_text_file",
            status="success",
            args_summary='{"path": "/tmp/a.txt"}',
            result_summary="done",
            start_time=fixed_time,
            end_time=fixed_time,
            elapsed_seconds=0.0,
        )
        item_two = ToolBatchItem(
            tool_id="t2",
            tool_name="mcp__filesystem__write_file",
            display_name="write_file",
            status="success",
            args_summary='{"path": "/tmp/b.txt"}',
            result_summary="ok",
            start_time=fixed_time,
            end_time=fixed_time,
            elapsed_seconds=0.0,
        )
        batch.add_tool(item_one)
        batch.add_tool(item_two)


def test_timeline_snapshot_batch_card(snap_compare, monkeypatch) -> None:  # noqa: ANN001 - pytest fixture type
    """Snapshot for batched MCP tool presentation."""
    _configure_snapshot_terminal_environment(monkeypatch)
    assert snap_compare(
        _TimelineBatchSnapshotApp(),
        terminal_size=(120, 32),
        run_before=_settle_scaffold_snapshot,
    )


def _configure_real_tui_snapshot_environment(monkeypatch) -> None:  # noqa: ANN001 - pytest fixture type
    _configure_snapshot_terminal_environment(monkeypatch)
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )


def _build_real_tui_snapshot_app(tmp_path: Path) -> App:
    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "claude-sonnet-4-5"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Create a poem about Bob Dylan and write it to a file in my workspace.",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app
    return app


def _build_real_tui_multi_agent_snapshot_app(tmp_path: Path) -> App:
    display = TextualTerminalDisplay(
        ["agent_a", "agent_b"],
        agent_models={
            "agent_a": "claude-sonnet-4-5",
            "agent_b": "gpt-5.3-codex",
        },
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Evaluate both answers and merge the strongest reasoning.",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app
    return app


def _stop_round_timers_if_running(app: App) -> None:
    ribbon = getattr(app, "_status_ribbon", None)
    if not ribbon:
        return

    if hasattr(ribbon, "stop_all_round_timers"):
        ribbon.stop_all_round_timers()
    timer_handle = getattr(ribbon, "_timer_handle", None)
    if timer_handle:
        timer_handle.stop()
        ribbon._timer_handle = None


def _stop_all_tui_timers(app: App) -> None:
    """Stop recurring timers so full-app snapshots stay deterministic."""
    auto_refresh_timer = getattr(app, "_auto_refresh_timer", None)
    if auto_refresh_timer:
        auto_refresh_timer.stop()
        app._auto_refresh_timer = None

    for timer in list(getattr(app, "_timers", [])):
        try:
            timer.stop()
        except Exception:
            pass


def _complete_tool_appearance_states(app: App) -> None:
    """Force tool cards to their post-animation state before capture."""
    for card in app.query(CollapsibleTextCard):
        card._complete_appearance()
        refresh_timer = getattr(card, "_refresh_timer", None)
        if refresh_timer:
            refresh_timer.stop()
            card._refresh_timer = None
            card._refresh_pending = False

    for card in app.query(ToolCallCard):
        card._complete_appearance()

    for batch in app.query(ToolBatchCard):
        batch._complete_appearance()

    for card in app.query(SubagentCard):
        card._complete_appearance()
        poll_timer = getattr(card, "_poll_timer", None)
        if poll_timer:
            poll_timer.stop()
            card._poll_timer = None


def _make_snapshot_subagent(
    subagent_id: str,
    *,
    status: str,
    task: str,
    elapsed_seconds: float,
    timeout_seconds: float,
    answer_preview: str | None = None,
) -> SubagentDisplayData:
    return SubagentDisplayData(
        id=subagent_id,
        task=task,
        status=status,
        progress_percent=0,
        elapsed_seconds=elapsed_seconds,
        timeout_seconds=timeout_seconds,
        workspace_path="",
        workspace_file_count=0,
        last_log_line="",
        error=None,
        answer_preview=answer_preview,
        log_path=None,
    )


async def _seed_real_tui_round_snapshot(pilot) -> None:  # noqa: ANN001 - fixture-provided type
    app = pilot.app
    panel = app.agent_widgets["agent_a"]
    panel._hide_loading()
    _stop_round_timers_if_running(app)

    timeline = panel._get_timeline()
    assert timeline is not None
    fixed_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

    timeline.add_text(
        "I'll create a poem about Bob Dylan and write it to a file in my workspace.",
        text_class="content-inline",
        round_number=1,
    )

    tool_running = ToolDisplayData(
        tool_id="t_real",
        tool_name="Write",
        display_name="Write",
        tool_type="tool",
        category="workspace",
        icon="W",
        color="green",
        status="running",
        start_time=fixed_time,
        args_summary='{"file_path": "/workspace/deliverable/final.txt"}',
        args_full='{"file_path": "/workspace/deliverable/final.txt"}',
    )
    timeline.add_tool(tool_running, round_number=1)

    tool_done = ToolDisplayData(
        tool_id="t_real",
        tool_name="Write",
        display_name="Write",
        tool_type="tool",
        category="workspace",
        icon="W",
        color="green",
        status="success",
        start_time=fixed_time,
        end_time=fixed_time,
        args_summary='{"file_path": "/workspace/deliverable/final.txt"}',
        args_full='{"file_path": "/workspace/deliverable/final.txt"}',
        result_summary="File created",
        result_full="File created",
        elapsed_seconds=0.8,
    )
    timeline.update_tool("t_real", tool_done)

    timeline.add_text(
        "The file has been saved to the deliverable folder and is ready for use.",
        text_class="content-inline",
        round_number=1,
    )
    app.query_one("#timeout_display", Label).update("⏱ 0:00 / 10:00")
    app.query_one("#status_cwd", Static).update("[dim]📁[/] /workspace")
    app.set_focus(None)
    _complete_tool_appearance_states(app)
    _stop_all_tui_timers(app)
    await pilot.pause()


def test_timeline_snapshot_real_tui_round_view(snap_compare, monkeypatch, tmp_path: Path) -> None:
    """Snapshot of the runtime Textual app shell with agent panel content."""
    _configure_real_tui_snapshot_environment(monkeypatch)
    assert snap_compare(
        _build_real_tui_snapshot_app(tmp_path),
        terminal_size=(140, 42),
        run_before=_seed_real_tui_round_snapshot,
    )


async def _seed_real_tui_toast_snapshot(pilot) -> None:  # noqa: ANN001 - fixture-provided type
    app = pilot.app
    panel = app.agent_widgets["agent_a"]
    panel._hide_loading()
    _stop_round_timers_if_running(app)

    app.query_one("#timeout_display", Label).update("⏱ 0:00 / 10:00")
    app.query_one("#status_cwd", Static).update("[dim]📁[/] /workspace")
    app.set_focus(None)

    app.notify("Info: collecting agent updates", severity="information", timeout=30)
    app.notify("Warning: context budget is nearly full", severity="warning", timeout=30)
    app.notify("Error: failed to parse plan metadata", severity="error", timeout=30)
    app.notify("Success: final answer saved", severity="success", timeout=30)

    await pilot.pause()
    _stop_all_tui_timers(app)
    await pilot.pause()


def test_timeline_snapshot_real_tui_toast_stack(snap_compare, monkeypatch, tmp_path: Path) -> None:
    """Snapshot of runtime Textual app with stacked toast severities."""
    _configure_real_tui_snapshot_environment(monkeypatch)
    assert snap_compare(
        _build_real_tui_snapshot_app(tmp_path),
        terminal_size=(140, 42),
        run_before=_seed_real_tui_toast_snapshot,
    )


async def _seed_real_tui_runtime_injection_snapshot(pilot) -> None:  # noqa: ANN001 - fixture-provided type
    app = pilot.app
    app.agent_widgets["agent_a"]._hide_loading()
    app.agent_widgets["agent_b"]._hide_loading()
    _stop_round_timers_if_running(app)

    # Show per-agent queued runtime injection status in the tab bar and banner.
    assert app._tab_bar is not None
    app._tab_bar.set_pending_injection_counts({"agent_a": 0, "agent_b": 1})

    banner = app._queued_input_banner
    if banner is None:
        banner = QueuedInputBanner(id="queued_input_banner")
        app._queued_input_banner = banner
        app._ensure_queued_input_banner_mounted()
    banner.set_messages(
        [
            {
                "id": 11,
                "content": "Please include edge-case handling in your revised answer.",
                "target_label": "all agents",
                "pending_agents": ["agent_b"],
            },
            {
                "id": 12,
                "content": "Also add one adversarial test case for malformed input.",
                "target_label": "all agents",
                "pending_agents": ["agent_b"],
            },
        ],
    )
    banner.set_pending_counts({"agent_b": 2})
    app._set_queued_input_region_visible(True)

    # Agent A already received the runtime message: add an explicit timeline entry.
    panel = app.agent_widgets["agent_a"]
    timeline = panel._get_timeline()
    assert timeline is not None
    timeline.add_text(
        "Runtime Injection #10 -> Delivered to agent_a: Please include edge-case handling in your revised answer.",
        text_class="status runtime-injection",
        round_number=1,
    )
    timeline.add_text(
        "Applied the requested edge-case checks and updated my draft accordingly.",
        text_class="content-inline",
        round_number=1,
    )

    app.query_one("#timeout_display", Label).update("⏱ 2:14 / 10:00")
    app.query_one("#status_cwd", Static).update("[dim]📁[/] /workspace")
    app.set_focus(None)
    _complete_tool_appearance_states(app)
    _stop_all_tui_timers(app)
    await pilot.pause()


def test_timeline_snapshot_real_tui_runtime_injection_queue_and_delivery(
    snap_compare,
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Snapshot of queued + injected runtime input with per-agent pending state."""
    _configure_real_tui_snapshot_environment(monkeypatch)
    assert snap_compare(
        _build_real_tui_multi_agent_snapshot_app(tmp_path),
        terminal_size=(150, 44),
        run_before=_seed_real_tui_runtime_injection_snapshot,
    )


async def _seed_real_tui_consensus_map_snapshot(pilot) -> None:  # noqa: ANN001 - fixture-provided type
    app = pilot.app
    app.agent_widgets["agent_a"]._hide_loading()
    app.agent_widgets["agent_b"]._hide_loading()
    _stop_round_timers_if_running(app)

    from massgen.events import EventType, MassGenEvent

    app._apply_consensus_event(
        MassGenEvent.create(
            EventType.ANSWER_SUBMITTED,
            agent_id="agent_a",
            answer_label="agent1.1",
            answer_number=1,
            content="Agent A answer",
        ),
    )
    app._apply_consensus_event(
        MassGenEvent.create(
            EventType.ANSWER_SUBMITTED,
            agent_id="agent_b",
            answer_label="agent2.1",
            answer_number=1,
            content="Agent B answer",
        ),
    )
    app._apply_consensus_event(
        MassGenEvent.create(
            EventType.VOTE,
            agent_id="agent_b",
            target_id="agent_a",
            reason="Clearer result",
            voted_for_label="agent1.1",
        ),
    )
    app._apply_consensus_event(
        MassGenEvent.create(
            EventType.WINNER_SELECTED,
            agent_id="agent_a",
            vote_results={"winner": "agent_a"},
        ),
    )
    app.query_one("#timeout_display", Label).update("⏱ 1:02 / 10:00")
    app.query_one("#status_cwd", Static).update("[dim]📁[/] /workspace")
    app.set_focus(None)
    _stop_all_tui_timers(app)
    await pilot.pause()


def test_timeline_snapshot_real_tui_consensus_map(
    snap_compare,
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Snapshot of the compact Consensus Map inside the runtime TUI shell."""
    _configure_real_tui_snapshot_environment(monkeypatch)
    assert snap_compare(
        _build_real_tui_multi_agent_snapshot_app(tmp_path),
        terminal_size=(150, 44),
        run_before=_seed_real_tui_consensus_map_snapshot,
    )
    consensus_map = Path(__file__).parent / "__snapshots__" / "test_timeline_snapshot_scaffold" / "test_timeline_snapshot_real_tui_consensus_map.svg"
    if consensus_map.exists():
        snapshot_text = consensus_map.read_text(encoding="utf-8")
        assert "Consensus" in snapshot_text
        assert "A&#160;wins" in snapshot_text


async def _seed_real_tui_subagent_input_bar_snapshot(pilot) -> None:  # noqa: ANN001 - fixture-provided type
    app = pilot.app
    panel = app.agent_widgets["agent_a"]
    panel._hide_loading()
    _stop_round_timers_if_running(app)

    from massgen.frontend.displays.textual_widgets.subagent_screen import SubagentScreen

    subagent = _make_snapshot_subagent(
        "parity_input_subagent",
        status="running",
        task="Refine edge-case tests while parent agent continues.",
        elapsed_seconds=38.0,
        timeout_seconds=300.0,
    )

    def _status_callback(_subagent_id: str) -> SubagentDisplayData:
        return subagent

    app._subagent_message_callback = lambda _subagent_id, _content, target_agents=None: True
    app.push_screen(
        SubagentScreen(
            subagent=subagent,
            all_subagents=[subagent],
            status_callback=_status_callback,
            send_message_callback=app._subagent_message_callback,
        ),
    )

    await pilot.pause()
    app.set_focus(None)
    _stop_all_tui_timers(app)
    await pilot.pause()


async def _seed_real_tui_subagent_runtime_queue_snapshot(pilot) -> None:  # noqa: ANN001 - fixture-provided type
    app = pilot.app
    panel = app.agent_widgets["agent_a"]
    panel._hide_loading()
    _stop_round_timers_if_running(app)

    from massgen.frontend.displays.textual_widgets.subagent_screen import (
        SubagentScreen,
        SubagentView,
    )

    subagent = _make_snapshot_subagent(
        "parity_queue_subagent",
        status="running",
        task="Refine runtime-injection handling while parent agent continues execution.",
        elapsed_seconds=71.0,
        timeout_seconds=300.0,
    )

    def _status_callback(_subagent_id: str) -> SubagentDisplayData:
        return subagent

    app._subagent_message_callback = lambda _subagent_id, _content, target_agents=None: True
    app.push_screen(
        SubagentScreen(
            subagent=subagent,
            all_subagents=[subagent],
            status_callback=_status_callback,
            send_message_callback=app._subagent_message_callback,
        ),
    )

    await pilot.pause()
    view = app.screen.query_one("#subagent-view", SubagentView)

    # Mirror main runtime queue semantics: multiple queued messages with mixed
    # delivery state so the compact "N messages queued" summary renders.
    view._inner_agents = ["agent_a", "agent_b"]
    view._queue_runtime_message(
        "Please add one adversarial test case for malformed runtime payloads.",
        target="all",
    )
    view._queue_runtime_message(
        "Also include an edge-case around empty tool-call arguments.",
        target="all",
    )
    # First message delivered to agent_a; second remains pending for both.
    view._mark_runtime_messages_delivered_for_agent(
        "agent_a",
        injection_content="[Human Input]: Please add one adversarial test case for malformed runtime payloads.",
    )
    assert len(view._queued_runtime_messages) == 2
    assert view._queued_runtime_banner is not None
    assert view._queued_runtime_region is not None
    assert "visible" in view._queued_runtime_region.classes

    app.set_focus(None)
    _stop_all_tui_timers(app)
    await pilot.pause()


def test_timeline_snapshot_real_tui_subagent_input_bar(
    snap_compare,
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Snapshot of SubagentScreen runtime input bar using main-app styling contract."""
    _configure_real_tui_snapshot_environment(monkeypatch)
    assert snap_compare(
        _build_real_tui_snapshot_app(tmp_path),
        terminal_size=(150, 44),
        run_before=_seed_real_tui_subagent_input_bar_snapshot,
    )


def test_timeline_snapshot_real_tui_subagent_runtime_injection_queue(
    snap_compare,
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Snapshot of SubagentScreen queued runtime-injection banner + input bar."""
    _configure_real_tui_snapshot_environment(monkeypatch)
    assert snap_compare(
        _build_real_tui_snapshot_app(tmp_path),
        terminal_size=(150, 44),
        run_before=_seed_real_tui_subagent_runtime_queue_snapshot,
    )
    snapshot_path = Path(__file__).parent / "__snapshots__" / "test_timeline_snapshot_scaffold" / "test_timeline_snapshot_real_tui_subagent_runtime_injection_queue.svg"
    snapshot_text = snapshot_path.read_text(encoding="utf-8")
    assert "2&#160;messages&#160;queued" in snapshot_text
    assert "Cancel&#160;latest" in snapshot_text
    assert "Clear&#160;queue" in snapshot_text
    queue_y_match = re.search(
        r'<text[^>]* y="([0-9.]+)"[^>]*>2&#160;messages&#160;queued</text>',
        snapshot_text,
    )
    running_y_match = re.search(
        r'<text[^>]* y="([0-9.]+)"[^>]*>Running&#160;\([0-9]+s\)&#160;&#160;</text>',
        snapshot_text,
    )
    assert queue_y_match is not None
    assert running_y_match is not None
    queue_y = float(queue_y_match.group(1))
    running_y = float(running_y_match.group(1))
    assert queue_y < running_y
    # Keep a thin visual separator between queue strip and running status row.
    assert (running_y - queue_y) >= 20
