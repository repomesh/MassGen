"""Unit tests for discriminative criteria emergence (bootstrap_criteria).

Covers:
- merge_proposals: dedup by exact 'text', FIFO eviction at cap, skips empty text.
- CoordinationConfig.criteria_mode validation and to_dict serialization.
- _resolve_effective_checklist_criteria augmentation when criteria_mode != "static".
- EvaluationSection emission instruction gating.
- AgentState.criteria_proposals field default.
"""

from __future__ import annotations

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
        text = self._render("bootstrap_inline")
        # Must instruct the agent to emit criteria the current answer does not satisfy.
        assert "proposed_criteria" in text or "propose criteria" in text.lower()
        assert "does not" in text.lower() or "not yet" in text.lower()

    def test_bootstrap_subagent_does_not_ask_agent_to_emit(self):
        text = self._render("bootstrap_subagent")
        # In subagent mode, a critic emits; the agents themselves should NOT
        # be asked to emit proposed_criteria.
        assert "proposed_criteria" not in text.lower()


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

    def test_subagent_mode_marks_notice_once(self):
        orch = self._make_full_orch("bootstrap_subagent")
        assert not getattr(orch, "_bootstrap_subagent_notice_logged", False)
        # Two drain calls should set the once-flag and not error.
        orch._drain_pending_criteria_proposals()
        orch._drain_pending_criteria_proposals()
        assert orch._bootstrap_subagent_notice_logged is True

    def test_subagent_mode_still_propagates_seeded_entries(self):
        orch = self._make_full_orch("bootstrap_subagent")
        # Seed the accumulator directly (test stand-in for the v0.1.86 LLM discriminator).
        orch._bootstrap_criteria_accumulator = [
            {"text": "Subagent-emitted gap criterion", "category": "primary"},
        ]
        items, *_ = orch._resolve_effective_checklist_criteria()
        assert "Subagent-emitted gap criterion" in items

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
