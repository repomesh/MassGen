"""Visual wiring tests for the standalone checkpoint MCP tool in the TUI.

The standalone server's `checkpoint` tool deserves the same hero-card treatment
as the in-orchestrator `checkpoint`. The standalone server's `init` tool
(housekeeping, called once at session start) does NOT.
"""

from __future__ import annotations

from massgen.frontend.displays.textual_widgets.tool_card import ToolCallCard


def test_standalone_checkpoint_tool_is_terminal():
    """The standalone server's `checkpoint` tool gets the hero card."""
    card = ToolCallCard(tool_name="mcp__massgen_checkpoint_standalone__checkpoint")
    assert card._detect_terminal_tool("mcp__massgen_checkpoint_standalone__checkpoint") is True


def test_internal_checkpoint_tool_is_terminal():
    """Regression: the in-orchestrator checkpoint stays a hero tool."""
    card = ToolCallCard(tool_name="mcp__massgen_checkpoint__checkpoint")
    assert card._detect_terminal_tool("mcp__massgen_checkpoint__checkpoint") is True


def test_bare_checkpoint_workflow_name_is_terminal():
    """The workflow-toolkit bare `checkpoint` name stays a hero tool."""
    card = ToolCallCard(tool_name="checkpoint")
    assert card._detect_terminal_tool("checkpoint") is True


def test_standalone_init_is_not_terminal():
    """The standalone `init` tool is housekeeping (one-time session setup) and
    must NOT get the hero card, even though its name contains 'checkpoint' as
    a substring of the server name."""
    card = ToolCallCard(tool_name="mcp__massgen_checkpoint_standalone__init")
    assert card._detect_terminal_tool("mcp__massgen_checkpoint_standalone__init") is False


def test_renderer_handles_standalone_objective_schema():
    """The hero renderer must read `objective` (standalone) when `task`
    (internal) is absent, so the standalone tool's hero card isn't blank."""
    import json

    card = ToolCallCard(tool_name="mcp__massgen_checkpoint_standalone__checkpoint")
    card._params_full = json.dumps(
        {
            "objective": "Decide whether to deploy v2.1 to prod",
            "eval_criteria": ["No DB schema changes", "Backup verified"],
        },
    )
    rendered = card._render_terminal_tool()
    plain = rendered.plain
    assert "Decide whether to deploy v2.1 to prod" in plain
    assert "No DB schema changes" in plain


def test_renderer_handles_standalone_action_goals_schema():
    """When `action_goals` is provided without `eval_criteria`, the renderer
    surfaces the action-goal count as a tag."""
    import json

    card = ToolCallCard(tool_name="mcp__massgen_checkpoint_standalone__checkpoint")
    card._params_full = json.dumps(
        {
            "objective": "Roll forward to v2.1",
            "action_goals": [
                {"id": "g1", "goal": "deploy"},
                {"id": "g2", "goal": "smoke-test"},
            ],
        },
    )
    plain = card._render_terminal_tool().plain
    assert "Roll forward to v2.1" in plain
    assert "2 action goals" in plain


def test_renderer_handles_standalone_plan_result():
    """The standalone tool's success result is `{plan: [...], logs_dir: ...}`,
    not `{message: ...}`. The renderer must summarize the plan length."""
    import json

    card = ToolCallCard(tool_name="mcp__massgen_checkpoint_standalone__checkpoint")
    card._params_full = json.dumps({"objective": "Decide deploy"})
    card._status = "success"
    card._result = json.dumps(
        {
            "status": "ok",
            "plan": [{"step": 1, "description": "verify backup"}, {"step": 2, "description": "deploy"}],
            "logs_dir": "/tmp/abc",
        },
    )
    plain = card._render_terminal_tool().plain
    assert "Plan returned (2 steps)" in plain
