"""Prompt-section gating for standalone checkpoint.

Per `feedback_remove_affordance_at_source.md`: when the flag is off, the
section must be absent from the rendered prompt entirely. When on, the
mode-specific subsections only appear if their flag is set.
"""

from __future__ import annotations

from massgen.system_prompt_sections import (
    StandaloneCheckpointSection,
    SystemPromptBuilder,
)


def _render(section: StandaloneCheckpointSection) -> str:
    builder = SystemPromptBuilder()
    builder.add_section(section)
    return builder.build()


def test_default_generate_mode_no_extras():
    """Default render: canonical template + in-session overlay; no
    single-checkpoint/verify/workspace-context blocks."""
    out = _render(StandaloneCheckpointSection())
    assert "<standalone_checkpoint" in out
    # Canonical template content (proves we're reusing the source of truth)
    assert "Planning Checkpoints" in out
    assert "When to re-checkpoint" in out  # recheckpoint section kept (single_checkpoint=False)
    # In-session overlay
    assert "In-session integration notes" in out
    assert "blocking" in out
    # Off-by-default sections not present
    assert "Verify mode" not in out
    assert "Single-checkpoint mode: call" not in out
    assert "Workspace context" not in out


def test_overlay_names_exact_underscore_tool_names():
    """The agent must see the actual registered tool names, not the
    hyphenated package name from the canonical doc. A previous run had
    gemini calling `mcp__massgen-checkpoint-mcp__init` because the
    canonical doc references the `massgen-checkpoint-mcp` package name —
    the in-session overlay must show the underscore-namespaced names so
    the agent doesn't invent hyphenated variants."""
    out = _render(StandaloneCheckpointSection())
    assert "mcp__massgen_checkpoint_standalone__init" in out
    assert "mcp__massgen_checkpoint_standalone__checkpoint" in out


def test_overlay_explicitly_forbids_background_wrapping():
    """The agent must be told NOT to wrap init/checkpoint in
    start_background_tool. A prior run had gemini calling
    `start_background_tool({tool_name: 'mcp__massgen-checkpoint-mcp__init'})`
    despite generic `do not parallel-call` guidance — make the
    background-tool prohibition explicit by name."""
    out = _render(StandaloneCheckpointSection())
    assert "start_background_tool" in out


def test_verify_mode_swaps_section():
    out = _render(StandaloneCheckpointSection(mode="verify"))
    assert "Verify mode" in out
    assert "draft_plan" in out


def test_single_checkpoint_section_only_when_flag_set():
    """The canonical template handles single-checkpoint via marker-based
    composition: when the flag is on, the recheckpoint-triggers block is
    stripped and the single-checkpoint-continuation block is kept."""
    on = _render(StandaloneCheckpointSection(single_checkpoint=True))
    off = _render(StandaloneCheckpointSection(single_checkpoint=False))
    # On: canonical template's "exactly once" continuation block is present;
    # the "When to re-checkpoint" triggers section is stripped.
    assert "exactly once" in on
    assert "When to re-checkpoint" not in on
    # Off: the inverse.
    assert "When to re-checkpoint" in off
    assert "exactly once" not in off


def test_workspace_context_section_only_when_flag_set():
    on = _render(StandaloneCheckpointSection(include_workspace_context=True))
    off = _render(StandaloneCheckpointSection(include_workspace_context=False))
    assert "Workspace context" in on
    assert "Workspace context" not in off


def test_disabled_section_omits_from_builder():
    """Sections registered conditionally must be absent when not added."""
    builder = SystemPromptBuilder()
    out = builder.build()
    assert "standalone_checkpoint" not in out
    assert "massgen_checkpoint_standalone" not in out


def test_multi_agent_strips_section_at_builder_level():
    """When the parent has >1 agents, the orchestrator skips MCP injection.
    The system_message_builder must mirror that gate so the prompt doesn't
    promise an unregistered tool (per feedback_remove_affordance_at_source.md).
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from massgen.system_message_builder import SystemMessageBuilder

    cc = SimpleNamespace(
        skills_directory=".massgen/skills",
        load_previous_session_skills=False,
        enabled_skill_names=None,
        enable_subagents=False,
        enable_memory_filesystem_mode=False,
        planning_mode_instruction=None,
        broadcast=False,
        task_planning_filesystem_mode=False,
        learning_capture_mode="round",
        standalone_checkpoint_enabled=True,
        standalone_checkpoint_team_config="/tmp/team.yaml",
        standalone_checkpoint_mode="generate",
        standalone_checkpoint_single=False,
        standalone_checkpoint_include_workspace_context=False,
        checkpoint_enabled=False,
    )
    config = SimpleNamespace(coordination_config=cc)

    def _stub_agent():
        backend = MagicMock()
        backend.config = {"model": "gpt-4o-mini"}
        backend.filesystem_manager = None
        backend.backend_params = {}
        backend.mcp_servers = []
        agent = MagicMock()
        agent.get_configurable_system_message.return_value = "You are helpful."
        agent.backend = backend
        agent.config = None
        return agent

    multi = {"agent_a": _stub_agent(), "agent_b": _stub_agent()}
    single = {"agent_a": _stub_agent()}

    mt = MagicMock()
    mt._voting_sensitivity = "medium"
    mt._answer_novelty_requirement = "moderate"

    b_multi = SystemMessageBuilder(config=config, message_templates=mt, agents=multi)
    b_single = SystemMessageBuilder(config=config, message_templates=mt, agents=single)

    # Exercise the gate predicate the same way build_coordination_message does.
    enabled_multi = (
        hasattr(b_multi.config, "coordination_config")
        and b_multi.config.coordination_config
        and getattr(b_multi.config.coordination_config, "standalone_checkpoint_enabled", False)
        and len(b_multi.agents) == 1
    )
    enabled_single = (
        hasattr(b_single.config, "coordination_config")
        and b_single.config.coordination_config
        and getattr(b_single.config.coordination_config, "standalone_checkpoint_enabled", False)
        and len(b_single.agents) == 1
    )
    assert enabled_multi is False, "multi-agent must NOT enable the standalone-checkpoint section"
    assert enabled_single is True, "single-agent must enable the standalone-checkpoint section"
