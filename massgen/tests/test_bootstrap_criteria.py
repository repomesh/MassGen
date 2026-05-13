"""Unit tests for discriminative criteria emergence (bootstrap_criteria).

Covers:
- merge_proposals: dedup by exact 'text', FIFO eviction at cap, skips empty text.
- CoordinationConfig.criteria_mode validation and to_dict serialization.
- _resolve_effective_checklist_criteria augmentation when criteria_mode != "static".
- EvaluationSection emission instruction gating.
- AgentState.criteria_proposals field default.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Pure merge logic (massgen/bootstrap_criteria.py)
# ---------------------------------------------------------------------------


class TestMergeProposals:
    def test_appends_new_proposals_to_empty_accumulator(self):
        from massgen.bootstrap_criteria import merge_proposals

        out = merge_proposals(
            [],
            [{"text": "Be specific about deadlines", "category": "standard"}],
            cap=10,
        )
        assert len(out) == 1
        assert out[0]["text"] == "Be specific about deadlines"

    def test_dedupes_by_exact_text(self):
        from massgen.bootstrap_criteria import merge_proposals

        existing = [{"text": "Cite sources", "category": "standard"}]
        new = [
            {"text": "Cite sources", "category": "primary"},  # duplicate text
            {"text": "Use active voice", "category": "stretch"},
        ]
        out = merge_proposals(existing, new, cap=10)
        texts = [p["text"] for p in out]
        assert texts == ["Cite sources", "Use active voice"]

    def test_dedupes_within_new_proposals(self):
        from massgen.bootstrap_criteria import merge_proposals

        new = [
            {"text": "Cite sources"},
            {"text": "Cite sources"},
        ]
        out = merge_proposals([], new, cap=10)
        assert len(out) == 1

    def test_skips_proposals_with_empty_text(self):
        from massgen.bootstrap_criteria import merge_proposals

        new = [
            {"text": ""},
            {"text": "   "},
            {"category": "standard"},  # no text key
            {"text": "Valid criterion"},
        ]
        out = merge_proposals([], new, cap=10)
        assert len(out) == 1
        assert out[0]["text"] == "Valid criterion"

    def test_fifo_eviction_at_cap(self):
        from massgen.bootstrap_criteria import merge_proposals

        existing = [{"text": f"c{i}"} for i in range(5)]
        new = [{"text": f"new{i}"} for i in range(3)]
        out = merge_proposals(existing, new, cap=5)
        # Oldest dropped first; newest 5 kept.
        texts = [p["text"] for p in out]
        assert texts == ["c3", "c4", "new0", "new1", "new2"]

    def test_cap_zero_means_unlimited(self):
        from massgen.bootstrap_criteria import merge_proposals

        existing = [{"text": f"c{i}"} for i in range(50)]
        out = merge_proposals(existing, [{"text": "extra"}], cap=0)
        assert len(out) == 51

    def test_preserves_category_and_anti_patterns(self):
        from massgen.bootstrap_criteria import merge_proposals

        new = [
            {
                "text": "Concrete examples",
                "category": "primary",
                "anti_patterns": ["vague analogies"],
            },
        ]
        out = merge_proposals([], new, cap=10)
        assert out[0]["category"] == "primary"
        assert out[0]["anti_patterns"] == ["vague analogies"]


# ---------------------------------------------------------------------------
# CoordinationConfig: criteria_mode field + validation + serialization
# ---------------------------------------------------------------------------


class TestCoordinationConfigCriteriaMode:
    def test_default_is_static(self):
        from massgen.agent_config import CoordinationConfig

        cfg = CoordinationConfig()
        assert cfg.criteria_mode == "static"

    def test_accepts_bootstrap_inline(self):
        from massgen.agent_config import CoordinationConfig

        cfg = CoordinationConfig(criteria_mode="bootstrap_inline")
        assert cfg.criteria_mode == "bootstrap_inline"

    def test_accepts_bootstrap_subagent(self):
        from massgen.agent_config import CoordinationConfig

        cfg = CoordinationConfig(criteria_mode="bootstrap_subagent")
        assert cfg.criteria_mode == "bootstrap_subagent"

    def test_invalid_value_raises(self):
        from massgen.agent_config import CoordinationConfig

        with pytest.raises(ValueError, match="criteria_mode"):
            CoordinationConfig(criteria_mode="evolutionary")

    def test_default_caps(self):
        from massgen.agent_config import CoordinationConfig

        cfg = CoordinationConfig()
        assert cfg.bootstrap_max_per_agent_per_round == 3
        assert cfg.bootstrap_max_total == 30

    def test_to_dict_round_trips_criteria_mode(self):
        from massgen.agent_config import AgentConfig, CoordinationConfig

        ac = AgentConfig(
            backend_params={"type": "claude", "model": "claude-sonnet-4-5"},
            coordination_config=CoordinationConfig(
                criteria_mode="bootstrap_inline",
                bootstrap_max_per_agent_per_round=2,
                bootstrap_max_total=15,
            ),
        )
        d = ac.to_dict()
        coord = d["coordination_config"]
        assert coord["criteria_mode"] == "bootstrap_inline"
        assert coord["bootstrap_max_per_agent_per_round"] == 2
        assert coord["bootstrap_max_total"] == 15


# ---------------------------------------------------------------------------
# AgentState.criteria_proposals field
# ---------------------------------------------------------------------------


class TestAgentStateCriteriaProposals:
    def test_default_is_empty_list(self):
        from massgen.orchestrator import AgentState

        s = AgentState()
        assert s.criteria_proposals == []

    def test_is_separate_per_instance(self):
        from massgen.orchestrator import AgentState

        a = AgentState()
        b = AgentState()
        a.criteria_proposals.append({"text": "x"})
        assert b.criteria_proposals == []


# ---------------------------------------------------------------------------
# _resolve_effective_checklist_criteria: accumulator augmentation
# ---------------------------------------------------------------------------


def _make_stub_orchestrator(
    *,
    criteria_mode: str,
    inline: list[dict] | None = None,
    preset: str | None = None,
    accumulator: list[dict] | None = None,
    generated: list | None = None,
    changedoc: bool = False,
):
    """Construct a minimal stub that supports _resolve_effective_checklist_criteria."""
    from massgen.agent_config import AgentConfig, CoordinationConfig
    from massgen.orchestrator import Orchestrator

    coord = CoordinationConfig(
        criteria_mode=criteria_mode,
        checklist_criteria_inline=inline,
        checklist_criteria_preset=preset,
    )
    ac = AgentConfig(
        backend_params={"type": "claude", "model": "claude-sonnet-4-5"},
        coordination_config=coord,
    )
    # Bypass full __init__; we only need a few attributes.
    orch = Orchestrator.__new__(Orchestrator)
    orch.config = ac
    orch._generated_evaluation_criteria = generated
    orch._bootstrap_criteria_accumulator = list(accumulator or [])
    orch._is_changedoc_enabled = lambda: changedoc  # type: ignore[attr-defined]
    orch._get_decomposition_criteria_for_agent = lambda _aid: None  # type: ignore[attr-defined]
    orch._is_decomposition_mode = lambda: False  # type: ignore[attr-defined]
    return orch


class TestResolveEffectiveCriteriaWithAccumulator:
    def test_static_mode_ignores_accumulator(self):
        orch = _make_stub_orchestrator(
            criteria_mode="static",
            accumulator=[{"text": "emergent1", "category": "standard"}],
        )
        items, *_ = orch._resolve_effective_checklist_criteria()
        # Static mode falls back to generic — accumulator must NOT appear.
        assert "emergent1" not in items

    def test_bootstrap_inline_appends_accumulator_to_inline(self):
        orch = _make_stub_orchestrator(
            criteria_mode="bootstrap_inline",
            inline=[{"text": "inline1", "category": "standard"}],
            accumulator=[{"text": "emergent1", "category": "standard"}],
        )
        items, _cats, _vby, source, *_ = orch._resolve_effective_checklist_criteria()
        assert "inline1" in items
        assert "emergent1" in items
        # Inline texts come first in resolved order.
        assert items.index("inline1") < items.index("emergent1")
        assert source == "inline"

    def test_bootstrap_inline_with_empty_accumulator_is_inline_only(self):
        orch = _make_stub_orchestrator(
            criteria_mode="bootstrap_inline",
            inline=[{"text": "inline1", "category": "standard"}],
            accumulator=[],
        )
        items, *_ = orch._resolve_effective_checklist_criteria()
        assert items == ["inline1"]

    def test_bootstrap_inline_with_no_base_source_uses_accumulator_only(self):
        orch = _make_stub_orchestrator(
            criteria_mode="bootstrap_inline",
            accumulator=[
                {"text": "emergent1", "category": "standard"},
                {"text": "emergent2", "category": "primary"},
            ],
        )
        items, _cats, _vby, source, *_ = orch._resolve_effective_checklist_criteria()
        assert "emergent1" in items
        assert "emergent2" in items
        assert source == "bootstrap"

    def test_bootstrap_subagent_also_uses_accumulator(self):
        orch = _make_stub_orchestrator(
            criteria_mode="bootstrap_subagent",
            accumulator=[{"text": "from_critic", "category": "standard"}],
        )
        items, *_ = orch._resolve_effective_checklist_criteria()
        assert "from_critic" in items


# ---------------------------------------------------------------------------
# EvaluationSection emission instruction gating
# ---------------------------------------------------------------------------


class TestEvaluationSectionEmissionInstruction:
    def _render(self, criteria_mode: str) -> str:
        """Render EvaluationSection prose for a given criteria_mode."""
        from massgen.system_prompt_sections import EvaluationSection

        section = EvaluationSection(
            voting_sensitivity="checklist_gated",
            voting_threshold=2,
            custom_checklist_items=["cite sources"],
            item_categories={"E1": "standard"},
            criteria_mode=criteria_mode,
        )
        return section.build_content()

    def test_static_mode_has_no_emission_instruction(self):
        text = self._render("static")
        # The phrase should be unique to bootstrap modes.
        assert "proposed_criteria" not in text.lower()

    def test_bootstrap_inline_includes_emission_instruction(self):
        text = self._render("bootstrap_inline").lower()
        # Must instruct the agent to surface new criteria the current answer
        # does not yet satisfy. Per CLAUDE.md anti-pattern we describe the
        # behavior, not the literal parameter name, so the assertions test
        # for the conceptual phrases rather than `proposed_criteria`.
        assert "criteria emergence" in text or "proposing new evaluation criteria" in text
        assert "not yet" in text or "do not yet" in text or "do not" in text

    def test_bootstrap_subagent_does_not_ask_agent_to_emit(self):
        text = self._render("bootstrap_subagent").lower()
        # In subagent mode, a critic emits; the agents themselves should NOT
        # be told to surface new criteria via the submission.
        assert "criteria emergence" not in text
        assert "proposing new evaluation criteria" not in text


# ---------------------------------------------------------------------------
# _drain_pending_criteria_proposals: per-agent buffers → orchestrator accumulator
# ---------------------------------------------------------------------------


class TestDrainPendingProposals:
    def _make_orch(self, *, criteria_mode: str, agent_proposals: dict[str, list[dict]]):
        from massgen.agent_config import AgentConfig, CoordinationConfig
        from massgen.orchestrator import AgentState, Orchestrator

        ac = AgentConfig(
            backend_params={"type": "claude", "model": "claude-sonnet-4-5"},
            coordination_config=CoordinationConfig(criteria_mode=criteria_mode),
        )
        orch = Orchestrator.__new__(Orchestrator)
        orch.config = ac
        orch._bootstrap_criteria_accumulator = []
        orch.agent_states = {}
        for aid, props in agent_proposals.items():
            s = AgentState()
            s.criteria_proposals = list(props)
            orch.agent_states[aid] = s
        return orch

    def test_drain_moves_proposals_into_accumulator(self):
        orch = self._make_orch(
            criteria_mode="bootstrap_inline",
            agent_proposals={
                "a1": [{"text": "from a1", "category": "standard"}],
                "a2": [{"text": "from a2", "category": "primary"}],
            },
        )
        orch._drain_pending_criteria_proposals()
        texts = sorted(p["text"] for p in orch._bootstrap_criteria_accumulator)
        assert texts == ["from a1", "from a2"]

    def test_drain_clears_agent_buffers(self):
        orch = self._make_orch(
            criteria_mode="bootstrap_inline",
            agent_proposals={"a1": [{"text": "from a1"}]},
        )
        orch._drain_pending_criteria_proposals()
        assert orch.agent_states["a1"].criteria_proposals == []

    def test_drain_is_noop_in_static_mode(self):
        orch = self._make_orch(
            criteria_mode="static",
            agent_proposals={"a1": [{"text": "from a1"}]},
        )
        orch._drain_pending_criteria_proposals()
        # Buffer NOT drained, accumulator NOT touched.
        assert orch._bootstrap_criteria_accumulator == []
        assert orch.agent_states["a1"].criteria_proposals == [{"text": "from a1"}]

    def test_drain_runs_in_subagent_mode(self):
        # Even in bootstrap_subagent (criteria come from a critic), if agent
        # buffers happen to have entries they should still flow through —
        # the drain treats both modes symmetrically.
        orch = self._make_orch(
            criteria_mode="bootstrap_subagent",
            agent_proposals={"a1": [{"text": "leak"}]},
        )
        orch._drain_pending_criteria_proposals()
        assert orch._bootstrap_criteria_accumulator and orch._bootstrap_criteria_accumulator[0]["text"] == "leak"


# ---------------------------------------------------------------------------
# End-to-end: round-N proposals visible to round-N+1 criteria resolution
# ---------------------------------------------------------------------------


class TestBootstrapEndToEnd:
    """Verifies the propagation path: agent_state proposal -> accumulator
    -> _resolve_effective_checklist_criteria -> appears in next round's criteria."""

    def _make_full_orch(self, criteria_mode: str):
        from massgen.agent_config import AgentConfig, CoordinationConfig
        from massgen.orchestrator import AgentState, Orchestrator

        ac = AgentConfig(
            backend_params={"type": "claude", "model": "claude-sonnet-4-5"},
            coordination_config=CoordinationConfig(
                criteria_mode=criteria_mode,
                checklist_criteria_inline=[
                    {"text": "Round-1 seed criterion", "category": "standard"},
                ],
            ),
        )
        orch = Orchestrator.__new__(Orchestrator)
        orch.config = ac
        orch._generated_evaluation_criteria = None
        orch._bootstrap_criteria_accumulator = []
        orch._bootstrap_round_index = 0
        orch.agent_states = {"a1": AgentState(), "a2": AgentState()}
        orch._is_changedoc_enabled = lambda: False  # type: ignore[attr-defined]
        orch._get_decomposition_criteria_for_agent = lambda _aid: None  # type: ignore[attr-defined]
        orch._is_decomposition_mode = lambda: False  # type: ignore[attr-defined]
        return orch

    def test_inline_round_n_emission_visible_to_round_n_plus_1(self):
        orch = self._make_full_orch("bootstrap_inline")
        # Round 1: each agent emits a proposal via submit_checklist handler
        # (simulated here by populating the AgentState buffer directly).
        orch.agent_states["a1"].criteria_proposals = [
            {"text": "Concrete examples over abstractions", "category": "primary"},
        ]
        orch.agent_states["a2"].criteria_proposals = [
            {"text": "State assumptions explicitly", "category": "standard"},
        ]

        # Round 2: orchestrator resolves criteria for the next prompt build.
        items, cats, _vby, source, _anti, _anchors = orch._resolve_effective_checklist_criteria("a1")

        assert "Round-1 seed criterion" in items
        assert "Concrete examples over abstractions" in items
        assert "State assumptions explicitly" in items
        # Inline + bootstrap accumulator coexist; source reports the base.
        assert source == "inline"
        # Per-agent buffers cleared after drain.
        assert orch.agent_states["a1"].criteria_proposals == []
        assert orch.agent_states["a2"].criteria_proposals == []
        # Accumulator now persists the proposals.
        accumulator_texts = {p["text"] for p in orch._bootstrap_criteria_accumulator}
        assert "Concrete examples over abstractions" in accumulator_texts
        assert "State assumptions explicitly" in accumulator_texts

    def test_subagent_mode_drain_does_not_invoke_critic(self):
        """The drain is for harvesting emitted proposals — it does NOT call
        the discriminator. The discriminator is triggered separately via
        _run_bootstrap_discriminator_step() from an async between-rounds path.
        Calling drain in subagent mode is a no-op for the critic path.
        """
        orch = self._make_full_orch("bootstrap_subagent")
        # Drain calls without any pending proposals or stdio JSONLs.
        orch._drain_pending_criteria_proposals()
        orch._drain_pending_criteria_proposals()
        # No errors, accumulator stays empty (no seeded entries here).
        assert orch._bootstrap_criteria_accumulator == []

    def test_subagent_mode_still_propagates_seeded_entries(self):
        orch = self._make_full_orch("bootstrap_subagent")
        # Seed the accumulator directly (test stand-in for the v0.1.86 LLM discriminator).
        orch._bootstrap_criteria_accumulator = [
            {"text": "Subagent-emitted gap criterion", "category": "primary"},
        ]
        items, *_ = orch._resolve_effective_checklist_criteria()
        assert "Subagent-emitted gap criterion" in items

    def test_session_end_drain_captures_late_stdio_emissions(self, tmp_path):
        """Late-round emissions (written to stdio JSONL after the last
        _resolve_effective_checklist_criteria call) must still reach the
        accumulator. A live run on 2026-05-11 showed codex emitted 6 criteria
        across rounds, zero reached the accumulator because no _resolve fired
        between codex's submissions and session end.

        The fix: Orchestrator._drain_at_session_end() runs unconditionally
        before final presentation.
        """
        import json
        from types import SimpleNamespace

        orch = self._make_full_orch("bootstrap_inline")
        # Simulate a backend that has emitted but the orchestrator hasn't
        # drained since (no _resolve called).
        specs_dir = tmp_path / "agent_b_temp"
        specs_dir.mkdir()
        specs_path = specs_dir / "checklist_specs.json"
        specs_path.write_text("{}", encoding="utf-8")
        jsonl_path = specs_dir / "proposed_criteria.jsonl"
        jsonl_path.write_text(
            json.dumps({"text": "Stranded late emission", "category": "primary"}) + "\n",
            encoding="utf-8",
        )
        orch.agents = {"agent_b": SimpleNamespace(backend=SimpleNamespace(_checklist_specs_path=str(specs_path)))}

        # Invoke the session-end hook directly.
        orch._drain_at_session_end()

        texts = {p["text"] for p in orch._bootstrap_criteria_accumulator}
        assert "Stranded late emission" in texts
        assert not jsonl_path.exists()

    def test_variant_b_discriminator_spawns_subagent_and_merges_criteria(self):
        """Variant B (bootstrap_subagent): _run_bootstrap_discriminator_step()
        spawns an in-process critic via SubagentManager, parses the response,
        and merges proposed_criteria into the accumulator.

        Mocks SubagentManager to avoid a real LLM call. The mock returns a
        well-formed criteria JSON; the test asserts the accumulator receives
        them.
        """
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock, patch

        orch = self._make_full_orch("bootstrap_subagent")
        # Stub the coordination tracker with one answer per agent.
        orch.coordination_tracker = SimpleNamespace(
            answers_by_agent={
                "a1": [SimpleNamespace(content="Answer from agent a1", agent_id="a1")],
                "a2": [SimpleNamespace(content="Answer from agent a2", agent_id="a2")],
            },
        )
        orch.current_task = "Design a logo"
        orch.session_id = "test-session"
        # Workspace + log dir don't matter when SubagentManager is mocked, but
        # the method may attempt to resolve them; stub minimal attributes.
        orch.agents = {
            "a1": SimpleNamespace(backend=SimpleNamespace(filesystem_manager=SimpleNamespace(cwd="/tmp/test_ws"))),
            "a2": SimpleNamespace(backend=SimpleNamespace(filesystem_manager=SimpleNamespace(cwd="/tmp/test_ws"))),
        }
        orch.orchestrator_id = "test-orch"

        # The mocked subagent answer — a critic-shaped response.
        fake_answer = """```json
{
  "criteria": [
    {"text": "Visual hierarchy: lead element must dominate the composition without crowding subordinate elements.", "category": "primary"},
    {"text": "Symbol coherence: every glyph must reinforce a single design intent.", "category": "standard"},
    {"text": "Color discipline: palette must stay below 4 hues with deliberate weight assignment.", "category": "standard"},
    {"text": "Stretch: design must be recognizable at 16px.", "category": "stretch"}
  ],
  "aspiration": "A logo that earns recall in under one glance."
}
```"""
        mock_manager = MagicMock()
        mock_manager.spawn_subagent = AsyncMock(return_value=SimpleNamespace(answer=fake_answer, success=True))

        with patch("massgen.subagent.manager.SubagentManager", return_value=mock_manager):
            count = asyncio.run(orch._run_bootstrap_discriminator_step())

        assert count >= 1, "discriminator should merge at least one new criterion"
        mock_manager.spawn_subagent.assert_called_once()
        spawn_kwargs = mock_manager.spawn_subagent.call_args.kwargs
        # Prompt should reference the current task and the agents' answers.
        prompt = spawn_kwargs.get("task", "") or (
            spawn_kwargs.get("task") if "task" in spawn_kwargs else mock_manager.spawn_subagent.call_args.args[0] if mock_manager.spawn_subagent.call_args.args else ""
        )
        assert "Design a logo" in prompt
        # Accumulator now contains the parsed criteria.
        texts = {p["text"] for p in orch._bootstrap_criteria_accumulator}
        assert any("Visual hierarchy" in t for t in texts)
        assert any("Symbol coherence" in t for t in texts)

    def test_variant_b_discriminator_skips_when_subagent_returns_failure(self):
        """A failed subagent (success=False) must NOT have its answer parsed
        — it may carry partial/error text that pollutes the accumulator."""
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock, patch

        orch = self._make_full_orch("bootstrap_subagent")
        orch.coordination_tracker = SimpleNamespace(
            answers_by_agent={"a1": [SimpleNamespace(content="An answer", agent_id="a1")]},
        )
        orch.current_task = "Test task"
        orch.session_id = "test"
        orch.orchestrator_id = "test-orch"
        orch.agents = {"a1": SimpleNamespace(backend=SimpleNamespace(filesystem_manager=SimpleNamespace(cwd="/tmp/test_ws")))}

        # Mock returns success=False with partial/error text — parser would
        # otherwise accept it.
        fake_answer = '{"criteria":[{"text":"Junk from failed run","category":"primary"}],"aspiration":"x"}'
        mock_manager = MagicMock()
        mock_manager.spawn_subagent = AsyncMock(
            return_value=SimpleNamespace(answer=fake_answer, success=False),
        )
        with patch("massgen.subagent.manager.SubagentManager", return_value=mock_manager):
            count = asyncio.run(orch._run_bootstrap_discriminator_step())
        assert count == 0
        assert orch._bootstrap_criteria_accumulator == []

    def test_maybe_run_discriminator_refires_on_changed_answers(self):
        """The dedup gate keys on (agent_id, content_hash) — when an agent
        emits a new answer the discriminator must fire again, not be silenced
        by an agent-id-only dedup."""
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        orch = self._make_full_orch("bootstrap_subagent")
        orch.coordination_tracker = SimpleNamespace(answers_by_agent={})
        orch.current_task = "Test task"
        orch.session_id = "test"
        orch.orchestrator_id = "test-orch"
        orch.agents = {"a1": SimpleNamespace(backend=SimpleNamespace(filesystem_manager=SimpleNamespace(cwd="/tmp/test_ws")))}

        spawn_calls = 0

        def make_answer():
            return SimpleNamespace(
                answer='{"criteria":[{"text":"X","category":"primary"}],"aspiration":"y"}',
                success=True,
            )

        mock_manager = MagicMock()

        async def _spawn(**_kwargs):
            nonlocal spawn_calls
            spawn_calls += 1
            return make_answer()

        mock_manager.spawn_subagent = _spawn

        with patch("massgen.subagent.manager.SubagentManager", return_value=mock_manager):
            # Round N — answer set v1
            orch.coordination_tracker.answers_by_agent = {
                "a1": [SimpleNamespace(content="answer v1", agent_id="a1")],
            }

            async def run_v1():
                return await orch._maybe_run_bootstrap_discriminator({"a1": "answer v1"})

            asyncio.run(run_v1())
            assert spawn_calls == 1

            # Same content → must NOT re-spawn.
            asyncio.run(orch._maybe_run_bootstrap_discriminator({"a1": "answer v1"}))
            assert spawn_calls == 1

            # New content from same agent → MUST re-spawn.
            orch.coordination_tracker.answers_by_agent = {
                "a1": [SimpleNamespace(content="answer v2", agent_id="a1")],
            }
            asyncio.run(orch._maybe_run_bootstrap_discriminator({"a1": "answer v2"}))
            assert spawn_calls == 2

    def test_bootstrap_inline_requires_checklist_gated_voting(self):
        """Misconfiguration: bootstrap_inline + non-checklist_gated voting
        means submit_checklist isn't registered → emission channel doesn't
        exist → feature silently no-ops for the whole session. Must raise
        ValueError at orchestrator init, not log a warning that's easy to miss.
        """
        from types import SimpleNamespace

        from massgen.agent_config import AgentConfig, CoordinationConfig
        from massgen.orchestrator import Orchestrator

        ac = AgentConfig(
            backend_params={"type": "claude", "model": "claude-sonnet-4-5"},
            voting_sensitivity="lenient",  # NOT checklist_gated
            coordination_config=CoordinationConfig(criteria_mode="bootstrap_inline"),
        )
        orch = Orchestrator.__new__(Orchestrator)
        orch.config = ac
        orch.agents = {"a1": SimpleNamespace(backend=SimpleNamespace())}
        with pytest.raises(ValueError, match="bootstrap_inline"):
            orch._init_checklist_tool()

    def test_bootstrap_inline_with_checklist_gated_does_not_raise(self):
        """Sanity: the well-formed combo proceeds past the early-exit check."""

        from massgen.agent_config import AgentConfig, CoordinationConfig
        from massgen.orchestrator import Orchestrator

        ac = AgentConfig(
            backend_params={"type": "claude", "model": "claude-sonnet-4-5"},
            voting_sensitivity="checklist_gated",
            voting_threshold=2,
            coordination_config=CoordinationConfig(criteria_mode="bootstrap_inline"),
        )
        orch = Orchestrator.__new__(Orchestrator)
        orch.config = ac
        orch.agents = {}  # empty → loop body skipped, but no raise

        # Should not raise even with empty agents (we only care the gate doesn't fire).
        orch._init_checklist_tool()

    def test_stdio_drain_preserves_fifo_order_under_cap(self, tmp_path):
        """Per-agent cap drops *later* entries, not random ones — verifies
        FIFO semantics."""
        import json
        from types import SimpleNamespace

        from massgen.agent_config import AgentConfig, CoordinationConfig
        from massgen.orchestrator import AgentState, Orchestrator

        coord = CoordinationConfig(
            criteria_mode="bootstrap_inline",
            bootstrap_max_per_agent_per_round=3,
            bootstrap_max_total=100,
        )
        ac = AgentConfig(
            backend_params={"type": "claude", "model": "claude-sonnet-4-5"},
            coordination_config=coord,
        )
        orch = Orchestrator.__new__(Orchestrator)
        orch.config = ac
        orch._generated_evaluation_criteria = None
        orch._bootstrap_criteria_accumulator = []
        orch.agent_states = {"a1": AgentState()}
        orch._is_changedoc_enabled = lambda: False  # type: ignore[attr-defined]
        orch._get_decomposition_criteria_for_agent = lambda _aid: None  # type: ignore[attr-defined]
        orch._is_decomposition_mode = lambda: False  # type: ignore[attr-defined]

        specs_dir = tmp_path / "agent_a_fifo"
        specs_dir.mkdir()
        specs_path = specs_dir / "checklist_specs.json"
        specs_path.write_text("{}", encoding="utf-8")
        jsonl_path = specs_dir / "proposed_criteria.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as fh:
            for i in range(10):
                fh.write(json.dumps({"text": f"entry_{i}", "category": "standard"}) + "\n")
        orch.agents = {"a1": SimpleNamespace(backend=SimpleNamespace(_checklist_specs_path=str(specs_path)))}

        orch._drain_pending_criteria_proposals()

        texts = [p["text"] for p in orch._bootstrap_criteria_accumulator]
        # Cap=3 keeps the FIRST 3 entries (FIFO), drops entries 3..9.
        assert texts == ["entry_0", "entry_1", "entry_2"]

    def test_multi_agent_content_hash_dedup_fires_per_agent(self):
        """Two-agent scenario: when only ONE agent's content changes, the
        discriminator must re-fire (content-hash signature catches the diff,
        not just the agent-id set)."""
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import patch

        orch = self._make_full_orch("bootstrap_subagent")
        orch.current_task = "Test"
        orch.session_id = "test"
        orch.orchestrator_id = "test-orch"
        orch.agents = {
            "a1": SimpleNamespace(backend=SimpleNamespace(filesystem_manager=SimpleNamespace(cwd="/tmp"))),
            "a2": SimpleNamespace(backend=SimpleNamespace(filesystem_manager=SimpleNamespace(cwd="/tmp"))),
        }
        # Tracker is consulted by _run_bootstrap_discriminator_step; mirror the
        # current_answers we pass to _maybe_run.
        orch.coordination_tracker = SimpleNamespace(
            answers_by_agent={
                "a1": [SimpleNamespace(content="v1", agent_id="a1")],
                "a2": [SimpleNamespace(content="v1", agent_id="a2")],
            },
        )

        spawn_count = 0

        async def _spawn(**_kwargs):
            nonlocal spawn_count
            spawn_count += 1
            return SimpleNamespace(
                answer='{"criteria":[{"text":"X","category":"primary"}],"aspiration":"y"}',
                success=True,
            )

        mock_manager = SimpleNamespace(spawn_subagent=_spawn)
        with patch("massgen.subagent.manager.SubagentManager", return_value=mock_manager):
            # Round 1: both agents at v1
            asyncio.run(orch._maybe_run_bootstrap_discriminator({"a1": "v1", "a2": "v1"}))
            assert spawn_count == 1

            # Round 2: a1 unchanged, a2 unchanged → no fire
            asyncio.run(orch._maybe_run_bootstrap_discriminator({"a1": "v1", "a2": "v1"}))
            assert spawn_count == 1

            # Round 3: a2 changed → must fire
            orch.coordination_tracker.answers_by_agent["a2"][-1].content = "v2"
            asyncio.run(orch._maybe_run_bootstrap_discriminator({"a1": "v1", "a2": "v2"}))
            assert spawn_count == 2

            # Round 4: a1 changed, a2 same as round 3 → must fire again
            orch.coordination_tracker.answers_by_agent["a1"][-1].content = "v3"
            asyncio.run(orch._maybe_run_bootstrap_discriminator({"a1": "v3", "a2": "v2"}))
            assert spawn_count == 3

    def test_stdio_drain_respects_per_agent_round_cap(self, tmp_path):
        """bootstrap_max_per_agent_per_round bounds how many entries the drain
        harvests from a single agent's JSONL in one pass — protects against a
        single rogue agent flooding the accumulator."""
        import json
        from types import SimpleNamespace

        from massgen.agent_config import AgentConfig, CoordinationConfig
        from massgen.orchestrator import AgentState, Orchestrator

        coord = CoordinationConfig(
            criteria_mode="bootstrap_inline",
            bootstrap_max_per_agent_per_round=3,
            bootstrap_max_total=100,
        )
        ac = AgentConfig(
            backend_params={"type": "claude", "model": "claude-sonnet-4-5"},
            coordination_config=coord,
        )
        orch = Orchestrator.__new__(Orchestrator)
        orch.config = ac
        orch._generated_evaluation_criteria = None
        orch._bootstrap_criteria_accumulator = []
        orch.agent_states = {"a1": AgentState()}
        orch._is_changedoc_enabled = lambda: False  # type: ignore[attr-defined]
        orch._get_decomposition_criteria_for_agent = lambda _aid: None  # type: ignore[attr-defined]
        orch._is_decomposition_mode = lambda: False  # type: ignore[attr-defined]

        specs_dir = tmp_path / "agent_a_spillover"
        specs_dir.mkdir()
        specs_path = specs_dir / "checklist_specs.json"
        specs_path.write_text("{}", encoding="utf-8")
        jsonl_path = specs_dir / "proposed_criteria.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as fh:
            for i in range(20):
                fh.write(json.dumps({"text": f"flood {i}", "category": "standard"}) + "\n")
        orch.agents = {"a1": SimpleNamespace(backend=SimpleNamespace(_checklist_specs_path=str(specs_path)))}

        orch._drain_pending_criteria_proposals()

        # Cap is 3 — accumulator must not pick up all 20.
        assert len(orch._bootstrap_criteria_accumulator) == 3
        assert not jsonl_path.exists()

    def test_variant_b_discriminator_skipped_when_not_subagent_mode(self):
        """static and bootstrap_inline modes must not invoke the discriminator."""
        import asyncio
        from unittest.mock import patch

        for mode in ("static", "bootstrap_inline"):
            orch = self._make_full_orch(mode)
            with patch("massgen.subagent.manager.SubagentManager") as mock_mgr_class:
                count = asyncio.run(orch._run_bootstrap_discriminator_step())
            assert count == 0
            mock_mgr_class.assert_not_called()

    def test_variant_b_discriminator_skipped_when_no_answers(self):
        """No answers in the tracker → discriminator is a no-op (nothing to critique)."""
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import patch

        orch = self._make_full_orch("bootstrap_subagent")
        orch.coordination_tracker = SimpleNamespace(answers_by_agent={})
        orch.current_task = "test"
        with patch("massgen.subagent.manager.SubagentManager") as mock_mgr_class:
            count = asyncio.run(orch._run_bootstrap_discriminator_step())
        assert count == 0
        mock_mgr_class.assert_not_called()

    def test_variant_b_discriminator_caps_subagent_at_one_answer(self, tmp_path):
        """The discriminator subagent should run a single answer with no
        refinement loop. Observed live in log_20260513_093905_671729: the
        subagent ran 2+ rounds with refinement (answer1.1 → answer1.2) and
        27 file-op tool calls before timing out at 180s, instead of emitting
        criteria JSON in one shot. The fix: pass max_new_answers_per_agent=1
        (and fast_iteration_mode=True) through SubagentOrchestratorConfig
        coordination.
        """
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock, patch

        orch = self._make_full_orch("bootstrap_subagent")
        orch.coordination_tracker = SimpleNamespace(
            answers_by_agent={"a1": [SimpleNamespace(content="An answer", agent_id="a1")]},
        )
        orch.current_task = "Test task"
        orch.session_id = "test"
        orch.orchestrator_id = "test-orch"
        agent_ws = tmp_path / "agent_ws"
        agent_ws.mkdir()
        orch.agents = {
            "a1": SimpleNamespace(backend=SimpleNamespace(filesystem_manager=SimpleNamespace(cwd=str(agent_ws)))),
        }

        captured_config = {}

        def capture_config(*args, **kwargs):
            captured_config["coordination"] = kwargs.get("coordination", {})
            return MagicMock(enabled=kwargs.get("enabled", True), agents=kwargs.get("agents", []))

        mock_manager = MagicMock()
        mock_manager.spawn_subagent = AsyncMock(
            return_value=SimpleNamespace(
                answer='{"criteria":[{"text":"x","category":"primary"}],"aspiration":"y"}',
                success=True,
            ),
        )
        with (
            patch(
                "massgen.subagent.models.SubagentOrchestratorConfig",
                side_effect=capture_config,
            ),
            patch("massgen.subagent.manager.SubagentManager", return_value=mock_manager),
        ):
            asyncio.run(orch._run_bootstrap_discriminator_step())

        coord = captured_config.get("coordination") or {}
        assert coord.get("max_new_answers_per_agent") == 1, f"discriminator subagent must cap at 1 answer (single-shot), got {coord}"
        # With a single critic agent the default voting_threshold=3 can never be
        # reached, so the subagent's orchestrator keeps entering vote/eval rounds
        # after the answer. voting_threshold=1 lets the agent's self-vote close
        # the run, and max_new_answers_global=1 is the hard cap.
        assert coord.get("voting_threshold") == 1, f"discriminator must lower voting_threshold so single-agent self-vote ends the run, got {coord}"
        assert coord.get("max_new_answers_global") == 1, f"discriminator must set max_new_answers_global=1 as a hard cap, got {coord}"

    def test_variant_b_discriminator_picks_up_criteria_json_artifact(self, tmp_path):
        """When the subagent writes criteria.json to its workspace, the
        discriminator should pick it up via find_precollab_artifact and merge
        from that artifact — mirroring the EvaluationCriteriaGenerator pattern.
        The answer-text fallback remains for backwards compat, but the file
        pickup path is preferred.
        """
        import asyncio
        import json
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock, patch

        orch = self._make_full_orch("bootstrap_subagent")
        orch.coordination_tracker = SimpleNamespace(
            answers_by_agent={"a1": [SimpleNamespace(content="An answer", agent_id="a1")]},
        )
        orch.current_task = "Test task"
        orch.session_id = "test"
        orch.orchestrator_id = "test-orch"
        agent_ws = tmp_path / "agent_ws"
        agent_ws.mkdir()
        orch.agents = {
            "a1": SimpleNamespace(backend=SimpleNamespace(filesystem_manager=SimpleNamespace(cwd=str(agent_ws)))),
        }

        # Build a criteria.json file the discriminator should pick up.
        artifact = tmp_path / "criteria.json"
        artifact.write_text(
            json.dumps(
                {
                    "aspiration": "Excellence",
                    "criteria": [
                        {"text": "From artifact: structural coherence wins", "category": "primary"},
                        {"text": "From artifact: avoid generic cliches", "category": "standard"},
                    ],
                },
            ),
            encoding="utf-8",
        )

        # Empty / generic answer text — must NOT be used when artifact exists.
        mock_manager = MagicMock()
        mock_manager.spawn_subagent = AsyncMock(
            return_value=SimpleNamespace(answer="(no JSON in answer text)", success=True),
        )

        with (
            patch("massgen.subagent.manager.SubagentManager", return_value=mock_manager),
            patch(
                "massgen.precollab_utils.find_precollab_artifact",
                return_value=artifact,
            ),
            patch("massgen.orchestrator.get_log_session_dir", return_value=str(tmp_path)),
        ):
            count = asyncio.run(orch._run_bootstrap_discriminator_step())

        assert count == 2, "discriminator should merge both artifact criteria"
        texts = {p["text"] for p in orch._bootstrap_criteria_accumulator}
        assert any("From artifact: structural coherence" in t for t in texts)
        assert any("From artifact: avoid generic cliches" in t for t in texts)

    def test_variant_b_discriminator_prompt_instructs_write_criteria_json(self, tmp_path):
        """The discriminator prompt must instruct the subagent to write
        criteria.json to its workspace so the parent can pick it up — the
        canonical file-pickup pattern used elsewhere (persona / criteria
        generators).
        """
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock, patch

        orch = self._make_full_orch("bootstrap_subagent")
        orch.coordination_tracker = SimpleNamespace(
            answers_by_agent={"a1": [SimpleNamespace(content="An answer", agent_id="a1")]},
        )
        orch.current_task = "Test task"
        orch.session_id = "test"
        orch.orchestrator_id = "test-orch"
        agent_ws = tmp_path / "agent_ws"
        agent_ws.mkdir()
        orch.agents = {
            "a1": SimpleNamespace(backend=SimpleNamespace(filesystem_manager=SimpleNamespace(cwd=str(agent_ws)))),
        }
        mock_manager = MagicMock()
        mock_manager.spawn_subagent = AsyncMock(
            return_value=SimpleNamespace(answer='{"criteria":[],"aspiration":"x"}', success=True),
        )

        with patch("massgen.subagent.manager.SubagentManager", return_value=mock_manager):
            asyncio.run(orch._run_bootstrap_discriminator_step())

        prompt = mock_manager.spawn_subagent.call_args.kwargs.get("task", "") or (mock_manager.spawn_subagent.call_args.args[0] if mock_manager.spawn_subagent.call_args.args else "")
        assert "criteria.json" in prompt, f"discriminator prompt must reference criteria.json (the artifact filename); got: {prompt[:500]}"

    def test_variant_b_discriminator_writes_context_md_before_spawn(self, tmp_path):
        """SubagentManager.spawn_subagent fails with "CONTEXT.md not found in
        workspace" unless the parent_workspace it's pointed at contains a
        CONTEXT.md. Observed live in log_20260513_090725_683824 — all three
        bootstrap_discriminator_N spawns failed for this reason.

        Regression: the discriminator must materialize CONTEXT.md at the
        parent_workspace passed to SubagentManager BEFORE spawn_subagent is
        called.
        """
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock, patch

        orch = self._make_full_orch("bootstrap_subagent")
        orch.coordination_tracker = SimpleNamespace(
            answers_by_agent={"a1": [SimpleNamespace(content="An answer", agent_id="a1")]},
        )
        orch.current_task = "Design a logo"
        orch.session_id = "test"
        orch.orchestrator_id = "test-orch"
        # Use a real temp dir so CONTEXT.md materialization is observable.
        agent_workspace = tmp_path / "agent_workspace"
        agent_workspace.mkdir()
        orch.agents = {
            "a1": SimpleNamespace(
                backend=SimpleNamespace(filesystem_manager=SimpleNamespace(cwd=str(agent_workspace))),
            ),
        }

        captured_parent_workspace = {}

        def capture_manager(**kwargs):
            captured_parent_workspace["path"] = kwargs.get("parent_workspace")
            mgr = MagicMock()
            mgr.spawn_subagent = AsyncMock(
                return_value=SimpleNamespace(
                    answer='{"criteria":[{"text":"x","category":"primary"}],"aspiration":"y"}',
                    success=True,
                ),
            )
            return mgr

        with patch("massgen.subagent.manager.SubagentManager", side_effect=capture_manager):
            asyncio.run(orch._run_bootstrap_discriminator_step())

        parent_ws = captured_parent_workspace.get("path")
        assert parent_ws, "SubagentManager must be constructed with a parent_workspace"
        ctx_md = Path(parent_ws) / "CONTEXT.md"
        assert ctx_md.exists(), (
            f"CONTEXT.md must exist at the parent_workspace passed to SubagentManager " f"(checked {ctx_md}); otherwise spawn_subagent fails with " f"'CONTEXT.md not found in workspace'"
        )
        # The discriminator's CONTEXT.md should reference the task so the
        # subagent has minimum context.
        assert "Design a logo" in ctx_md.read_text(encoding="utf-8")

    def test_stdio_emissions_jsonl_drains_into_accumulator(self, tmp_path):
        """Non-SDK backends (gemini/codex/etc.) emit by appending to
        proposed_criteria.jsonl next to their checklist specs. The drain
        harvests, dedupes, and truncates the file so re-runs don't double-merge.
        """
        import json
        from types import SimpleNamespace

        orch = self._make_full_orch("bootstrap_inline")
        specs_dir = tmp_path / "stdio_agent"
        specs_dir.mkdir()
        specs_path = specs_dir / "specs.json"
        specs_path.write_text("{}", encoding="utf-8")
        jsonl_path = specs_dir / "proposed_criteria.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({"text": "From stdio agent A", "category": "primary"}) + "\n")
            fh.write(json.dumps({"text": "From stdio agent A", "category": "primary"}) + "\n")  # dup
            fh.write(json.dumps({"text": "  ", "category": "standard"}) + "\n")  # empty after strip
            fh.write(json.dumps({"text": "Another gap criterion"}) + "\n")
        backend = SimpleNamespace(_checklist_specs_path=str(specs_path))
        orch.agents = {"stdio_a": SimpleNamespace(backend=backend)}

        orch._drain_pending_criteria_proposals()

        texts = {p["text"] for p in orch._bootstrap_criteria_accumulator}
        assert "From stdio agent A" in texts
        assert "Another gap criterion" in texts
        # Empty-text and duplicate filtered.
        assert len(orch._bootstrap_criteria_accumulator) == 2
        # File truncated so the next drain doesn't re-merge.
        assert not jsonl_path.exists()
