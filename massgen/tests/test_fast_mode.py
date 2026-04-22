"""Tests for `--fast` CLI mode and its composable coordination fields.

`--fast` is a preset that enables several orthogonal speed knobs. Each knob is
independent and can be set directly via YAML; `--fast` just fills in sensible
defaults when YAML doesn't already specify them.

Covers:
- CoordinationConfig fields:
    * max_verifications_per_round
    * max_internal_fix_loops
    * skip_redundant_scaffolding
- AgentConfig.to_dict() round-trip for the three fields
- _parse_coordination_config() reading from YAML dict
- apply_mode_flags_to_config() behavior for --fast (preset, YAML wins)
- System prompt conditional sections driven by the three fields
"""

from __future__ import annotations

import argparse

from massgen.agent_config import AgentConfig, CoordinationConfig
from massgen.cli import _parse_coordination_config, apply_mode_flags_to_config

# ---------------------------------------------------------------------------
# CoordinationConfig field tests
# ---------------------------------------------------------------------------


class TestCoordinationConfigFastFields:
    def test_max_verifications_per_round_default_is_none(self):
        config = CoordinationConfig()
        assert config.max_verifications_per_round is None

    def test_max_internal_fix_loops_default_is_none(self):
        config = CoordinationConfig()
        assert config.max_internal_fix_loops is None

    def test_skip_redundant_scaffolding_default_is_false(self):
        config = CoordinationConfig()
        assert config.skip_redundant_scaffolding is False

    def test_can_set_max_verifications_per_round(self):
        config = CoordinationConfig(max_verifications_per_round=1)
        assert config.max_verifications_per_round == 1

    def test_can_set_max_internal_fix_loops(self):
        config = CoordinationConfig(max_internal_fix_loops=0)
        assert config.max_internal_fix_loops == 0

    def test_can_set_skip_redundant_scaffolding(self):
        config = CoordinationConfig(skip_redundant_scaffolding=True)
        assert config.skip_redundant_scaffolding is True

    def test_fields_are_orthogonal(self):
        """Setting one fast field should not implicitly set another."""
        config = CoordinationConfig(max_verifications_per_round=2)
        assert config.max_internal_fix_loops is None
        assert config.skip_redundant_scaffolding is False
        assert config.fast_iteration_mode is False


# ---------------------------------------------------------------------------
# _parse_coordination_config YAML parsing tests
# ---------------------------------------------------------------------------


class TestParseCoordinationConfigFastFields:
    def test_parses_max_verifications_per_round(self):
        cfg = _parse_coordination_config({"max_verifications_per_round": 1})
        assert cfg.max_verifications_per_round == 1

    def test_parses_max_internal_fix_loops(self):
        cfg = _parse_coordination_config({"max_internal_fix_loops": 0})
        assert cfg.max_internal_fix_loops == 0

    def test_parses_skip_redundant_scaffolding(self):
        cfg = _parse_coordination_config({"skip_redundant_scaffolding": True})
        assert cfg.skip_redundant_scaffolding is True

    def test_absent_keys_use_defaults(self):
        cfg = _parse_coordination_config({})
        assert cfg.max_verifications_per_round is None
        assert cfg.max_internal_fix_loops is None
        assert cfg.skip_redundant_scaffolding is False

    def test_parses_all_three_together(self):
        cfg = _parse_coordination_config(
            {
                "max_verifications_per_round": 1,
                "max_internal_fix_loops": 0,
                "skip_redundant_scaffolding": True,
            },
        )
        assert cfg.max_verifications_per_round == 1
        assert cfg.max_internal_fix_loops == 0
        assert cfg.skip_redundant_scaffolding is True


# ---------------------------------------------------------------------------
# AgentConfig.to_dict() round-trip tests
# ---------------------------------------------------------------------------


class TestAgentConfigToDictFastFields:
    def test_to_dict_includes_max_verifications_per_round(self):
        agent_cfg = AgentConfig(
            coordination_config=CoordinationConfig(max_verifications_per_round=1),
        )
        serialized = agent_cfg.to_dict()
        assert serialized["coordination_config"]["max_verifications_per_round"] == 1

    def test_to_dict_includes_max_internal_fix_loops(self):
        agent_cfg = AgentConfig(
            coordination_config=CoordinationConfig(max_internal_fix_loops=0),
        )
        serialized = agent_cfg.to_dict()
        assert serialized["coordination_config"]["max_internal_fix_loops"] == 0

    def test_to_dict_includes_skip_redundant_scaffolding(self):
        agent_cfg = AgentConfig(
            coordination_config=CoordinationConfig(skip_redundant_scaffolding=True),
        )
        serialized = agent_cfg.to_dict()
        assert serialized["coordination_config"]["skip_redundant_scaffolding"] is True

    def test_to_dict_defaults_are_serialized(self):
        agent_cfg = AgentConfig()
        serialized = agent_cfg.to_dict()
        assert serialized["coordination_config"]["max_verifications_per_round"] is None
        assert serialized["coordination_config"]["max_internal_fix_loops"] is None
        assert serialized["coordination_config"]["skip_redundant_scaffolding"] is False


# ---------------------------------------------------------------------------
# --fast CLI preset tests
# ---------------------------------------------------------------------------


def _make_args(**overrides) -> argparse.Namespace:
    """Build an argparse Namespace with CLI flag defaults."""
    defaults = {
        "coordination_mode": None,
        "quick": False,
        "personas": None,
        "single_agent": None,
        "fast": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestApplyFastFlagToConfig:
    def test_fast_flag_sets_fast_iteration_mode(self):
        config: dict = {}
        apply_mode_flags_to_config(config, _make_args(fast=True))
        assert config["orchestrator"]["coordination"]["fast_iteration_mode"] is True

    def test_fast_flag_sets_max_verifications_per_round_to_1(self):
        config: dict = {}
        apply_mode_flags_to_config(config, _make_args(fast=True))
        assert config["orchestrator"]["coordination"]["max_verifications_per_round"] == 1

    def test_fast_flag_sets_max_internal_fix_loops_to_0(self):
        config: dict = {}
        apply_mode_flags_to_config(config, _make_args(fast=True))
        assert config["orchestrator"]["coordination"]["max_internal_fix_loops"] == 0

    def test_fast_flag_sets_skip_redundant_scaffolding_true(self):
        config: dict = {}
        apply_mode_flags_to_config(config, _make_args(fast=True))
        assert config["orchestrator"]["coordination"]["skip_redundant_scaffolding"] is True

    def test_fast_absent_leaves_config_untouched(self):
        config: dict = {}
        apply_mode_flags_to_config(config, _make_args(fast=False))
        # No fast-related keys should be inserted
        if "orchestrator" in config and "coordination" in config["orchestrator"]:
            coord = config["orchestrator"]["coordination"]
            assert "fast_iteration_mode" not in coord
            assert "max_verifications_per_round" not in coord
            assert "max_internal_fix_loops" not in coord
            assert "skip_redundant_scaffolding" not in coord

    def test_yaml_value_wins_over_fast_preset_for_max_verifications(self):
        """Explicit YAML values should beat --fast defaults."""
        config = {
            "orchestrator": {"coordination": {"max_verifications_per_round": 3}},
        }
        apply_mode_flags_to_config(config, _make_args(fast=True))
        assert config["orchestrator"]["coordination"]["max_verifications_per_round"] == 3

    def test_yaml_value_wins_over_fast_preset_for_fix_loops(self):
        config = {
            "orchestrator": {"coordination": {"max_internal_fix_loops": 2}},
        }
        apply_mode_flags_to_config(config, _make_args(fast=True))
        assert config["orchestrator"]["coordination"]["max_internal_fix_loops"] == 2

    def test_yaml_value_wins_over_fast_preset_for_scaffolding(self):
        config = {
            "orchestrator": {"coordination": {"skip_redundant_scaffolding": False}},
        }
        apply_mode_flags_to_config(config, _make_args(fast=True))
        assert config["orchestrator"]["coordination"]["skip_redundant_scaffolding"] is False

    def test_yaml_value_wins_over_fast_preset_for_iteration_mode(self):
        config = {
            "orchestrator": {"coordination": {"fast_iteration_mode": False}},
        }
        apply_mode_flags_to_config(config, _make_args(fast=True))
        assert config["orchestrator"]["coordination"]["fast_iteration_mode"] is False

    def test_fast_composes_with_coordination_mode(self):
        """--fast alongside --coordination-mode should set both."""
        config: dict = {}
        apply_mode_flags_to_config(
            config,
            _make_args(fast=True, coordination_mode="parallel"),
        )
        assert config["orchestrator"]["coordination_mode"] == "voting"
        assert config["orchestrator"]["coordination"]["fast_iteration_mode"] is True


# ---------------------------------------------------------------------------
# System prompt conditional section tests
# ---------------------------------------------------------------------------


class TestSystemPromptFastSections:
    """Tests that the relevant prompt sections appear only when fields are set.

    These tests import the helper(s) from system_prompt_sections lazily to keep
    the test module importable even if the helper is added later.
    """

    def test_verification_budget_section_absent_when_unset(self):
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=None,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        assert "verification" not in guidance.lower()
        assert "fix loop" not in guidance.lower()

    def test_verification_budget_section_present_when_set(self):
        """The verification rule is now framed as PHASE 1 of the round lifecycle."""
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=1,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        # PHASE 1 is where verification lives
        assert "PHASE 1" in guidance
        assert "next round" in guidance.lower() or "known gaps" in guidance.lower()

    def test_verification_section_defines_holistic_look_in_phase_1(self):
        """Under the phase model, PHASE 1 describes ONE holistic look covering
        the WHOLE inherited candidate. Multiple tool calls are fine within PHASE 1."""
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=1,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        guidance_l = guidance.lower()
        # PHASE 1 uses holistic-look language
        assert "holistic look" in guidance_l
        # And the concept of "widely OK within one session"
        assert "looking widely" in guidance_l or "many tool calls" in guidance_l or "same look" in guidance_l

    def test_verification_section_allows_retry_on_error(self):
        """Retrying a failed tool call with corrected args is part of the same look."""
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=1,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        guidance_l = guidance.lower()
        assert "retry" in guidance_l or "retrying" in guidance_l

    def test_verification_section_names_concrete_tools(self):
        """Agents need concrete tool names, not abstract 'verify'."""
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=1,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        assert "read_media" in guidance
        assert "pytest" in guidance or "screenshot" in guidance.lower()

    def test_fix_loop_section_present_when_zero_set(self):
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=None,
            max_internal_fix_loops=0,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        guidance_l = guidance.lower()
        assert "fix loop" in guidance_l
        # The prompt rules out fix loops — either by forbidding them directly
        # or by stating the three-phase model makes them impossible.
        assert "do not" in guidance_l or "don't" in guidance_l or "impossible" in guidance_l or "no cycle" in guidance_l

    def test_fix_loop_section_distinguishes_broken_vs_imperfect(self):
        """Rule is: repair if broken, defer if imperfect — both must be named."""
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=None,
            max_internal_fix_loops=0,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        guidance_l = guidance.lower()
        assert "broken" in guidance_l
        assert "imperfect" in guidance_l

    def test_scaffolding_cached_hint_absent_when_files_missing(self):
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=None,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=True,
            scaffolding_exists=False,
        )
        assert "already exist" not in guidance.lower()

    def test_scaffolding_cached_hint_present_when_files_exist(self):
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=None,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=True,
            scaffolding_exists=True,
        )
        assert "scaffolding" in guidance.lower() or "changedoc" in guidance.lower()
        # Agent is told to continue/append or that files already exist
        assert "already exist" in guidance.lower() or "continue" in guidance.lower() or "Append" in guidance

    def test_scaffolding_cached_hint_absent_when_flag_off(self):
        """Even with files present, if skip_redundant_scaffolding=False, no hint."""
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=None,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=False,
            scaffolding_exists=True,
        )
        assert "already exist" not in guidance.lower()

    def test_all_guidance_absent_when_everything_off(self):
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=None,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        assert guidance.strip() == ""

    def test_principle_header_present_when_any_knob_active(self):
        """The 'fix broken, defer imperfect' header leads whenever any knob is on."""
        from massgen.system_prompt_sections import build_fast_mode_guidance

        for kwargs in [
            {
                "max_verifications_per_round": 1,
                "max_internal_fix_loops": None,
                "skip_redundant_scaffolding": False,
                "scaffolding_exists": False,
            },
            {
                "max_verifications_per_round": None,
                "max_internal_fix_loops": 0,
                "skip_redundant_scaffolding": False,
                "scaffolding_exists": False,
            },
            {
                "max_verifications_per_round": None,
                "max_internal_fix_loops": None,
                "skip_redundant_scaffolding": True,
                "scaffolding_exists": True,
            },
        ]:
            guidance = build_fast_mode_guidance(**kwargs)
            assert "fix broken, defer imperfect" in guidance.lower(), f"principle header missing for {kwargs}"

    def test_principle_header_absent_when_all_knobs_off(self):
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=None,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        assert "fix broken" not in guidance.lower()

    def test_multiple_sections_combine(self):
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=1,
            max_internal_fix_loops=0,
            skip_redundant_scaffolding=True,
            scaffolding_exists=True,
        )
        guidance_l = guidance.lower()
        assert "verification" in guidance_l
        assert "fix loop" in guidance_l
        assert "scaffolding" in guidance_l or "changedoc" in guidance_l
        # And the closing 'why' rationale
        assert "rounds are cheap" in guidance_l

    # ------------------------------------------------------------------
    # Three-phase lifecycle (PHASE 1: verify inherited; PHASE 2: build;
    # PHASE 3: submit). Verification only happens in PHASE 1, and PHASE 1
    # is skipped for round 0. No look→adjust→look loops are possible
    # because BUILD and END phases explicitly forbid verification.
    # ------------------------------------------------------------------

    def test_three_phase_labels_present_when_verify_cap_set(self):
        """All three PHASE labels must appear in the lifecycle prompt."""
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=1,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        assert "PHASE 1" in guidance
        assert "PHASE 2" in guidance
        assert "PHASE 3" in guidance

    def test_phase_names_describe_lifecycle_intent(self):
        """Each phase has a concrete role — START-OF-ROUND / BUILD / END-OF-ROUND
        (or equivalent naming)."""
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=1,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        guidance_l = guidance.lower()
        assert "start-of-round" in guidance_l or "start of round" in guidance_l
        assert "build" in guidance_l
        assert "end-of-round" in guidance_l or "end of round" in guidance_l

    def test_round_0_skips_phase_1(self):
        """Round 0 has no inherited candidate to verify — PHASE 1 is skipped."""
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=1,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        guidance_l = guidance.lower()
        # Must explicitly mention round 0 skipping PHASE 1
        assert "round 0" in guidance_l
        assert "skip" in guidance_l

    def test_phase_2_forbids_verification(self):
        """BUILD phase must explicitly forbid verification calls — this is
        the structural rule that replaces the soft 'do not double-check' advice."""
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=1,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        guidance_l = guidance.lower()
        # PHASE 2 block must forbid verification
        assert "no verification" in guidance_l or "no read_media" in guidance_l
        # And direct the agent to record thoughts as Known Gaps instead
        assert "known gap" in guidance_l

    def test_phase_3_is_submit_only(self):
        """END-OF-ROUND phase must be described as submit-only, no verify."""
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=1,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        guidance_l = guidance.lower()
        # Phase 3 mentions "submit" and forbids "one last look"
        assert "submit" in guidance_l
        # Either says "no verification" in end-of-round context or "no one last look"
        assert "one last look" in guidance_l or "no verification" in guidance_l

    def test_verification_section_does_not_imply_tool_call_cap(self):
        """Per user correction, the budget is a session cap, NOT a tool-call cap.
        Phrasing implying 'only N tool calls' is wrong."""
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=1,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        guidance_l = guidance.lower()
        # These phrases would mislead the agent into under-calling during a single look
        forbidden_phrases = [
            "1 tool call per round",
            "one tool call per round",
            "tool-call budget",
            "tool call budget",
            "budget counter",
            "1/1 verify calls",
        ]
        for phrase in forbidden_phrases:
            assert phrase not in guidance_l, f"misleading phrase present: {phrase!r}"

    def test_broken_definition_uses_mechanical_tests(self):
        """BROKEN should be defined by concrete mechanical failure modes
        (won't render / error / empty), not by subjective judgment."""
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=None,
            max_internal_fix_loops=0,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        # Must include at least 2 concrete failure examples
        hits = 0
        for phrase in (
            "won't render",
            "blank",
            "stack trace",
            "syntax error",
            "empty",
            "errored",
            "error result",
        ):
            if phrase in guidance.lower():
                hits += 1
        assert hits >= 2, f"expected ≥2 concrete BROKEN examples, got {hits}"

    def test_broken_scope_is_functional_not_content(self):
        """BROKEN must be scoped to FUNCTIONAL INTEGRITY (artifact fails on a
        vanilla run), not CONTENT QUALITY. This is a principled distinction —
        the prompt should state it as a principle, not enumerate specific
        content-level examples (which overfit)."""
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=None,
            max_internal_fix_loops=0,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        guidance_l = guidance.lower()
        # The scope rule must name FUNCTIONAL INTEGRITY (or equivalent) as
        # BROKEN's domain and CONTENT QUALITY (or equivalent) as NOT BROKEN.
        assert "functional integrity" in guidance_l or "functional" in guidance_l, "BROKEN should be tied to functional integrity"
        assert "content quality" in guidance_l or "content" in guidance_l, "IMPERFECT should be tied to content quality (principle, not example)"

    def test_round_0_has_absolute_ban_on_self_verify(self):
        """Round 0 has no inherited candidate, so there is NOTHING to verify.
        Agents rationalize 'I should verify my own round 0 output' — the
        prompt must absolutely ban self-verification in round 0."""
        from massgen.system_prompt_sections import build_fast_mode_guidance

        guidance = build_fast_mode_guidance(
            max_verifications_per_round=1,
            max_internal_fix_loops=None,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        guidance_l = guidance.lower()
        # Must name "self-verify" or "own output" as the banned action
        assert "self-verify" in guidance_l or "self-verification" in guidance_l or "your own" in guidance_l or "own output" in guidance_l, "round 0 ban on self-verification not explicit"
        # Must include an absolute phrasing
        assert "no exception" in guidance_l or "banned" in guidance_l or "zero" in guidance_l


# ---------------------------------------------------------------------------
# EvolvingSkillsSection gating tests
# ---------------------------------------------------------------------------


class TestEvolvingSkillsSectionFastGating:
    def test_non_fast_preserves_until_loop_template(self):
        """Back-compat: with fast_iteration_mode=False, the existing
        'until polished / until quality meets bar / until working correctly'
        template MUST still render (no accidental breakage)."""
        from massgen.system_prompt_sections import EvolvingSkillsSection

        content = EvolvingSkillsSection(fast_iteration_mode=False).build_content()
        assert "until working correctly" in content
        assert "until polished" in content
        assert "until quality meets bar" in content or "until correct" in content

    def test_fast_mode_drops_until_loop_template(self):
        """When fast_iteration_mode=True, the 'until X' loop language MUST
        be gone (it's the canonical form of within-round imperfection-seeking)."""
        from massgen.system_prompt_sections import EvolvingSkillsSection

        content = EvolvingSkillsSection(fast_iteration_mode=True).build_content()
        assert "until working correctly" not in content
        assert "until polished" not in content
        assert "until quality meets bar" not in content
        assert "re-verify until" not in content

    def test_fast_mode_has_phase_aware_variant(self):
        """Fast mode emits a phase-aware verification template — verification
        happens in PHASE 1 of the NEXT round, not before submit."""
        from massgen.system_prompt_sections import EvolvingSkillsSection

        content = EvolvingSkillsSection(fast_iteration_mode=True).build_content()
        content_l = content.lower()
        assert "known gaps" in content_l
        # Phase-aware: either names PHASE 1 or frames verify as next-round work
        assert "phase 1" in content_l or "next round" in content_l or "start-of-round" in content_l or "start of round" in content_l

    def test_default_fast_iteration_mode_is_false(self):
        """EvolvingSkillsSection() with no arg must default to the full template."""
        from massgen.system_prompt_sections import EvolvingSkillsSection

        content = EvolvingSkillsSection().build_content()
        assert "until working correctly" in content


# ---------------------------------------------------------------------------
# FastModeGuidanceSection priority test
# ---------------------------------------------------------------------------


class TestFastModeGuidanceSectionPriority:
    def test_priority_is_one_so_it_renders_before_output_first(self):
        """FastModeGuidanceSection must render BEFORE OutputFirstVerificationSection
        so the fast-mode rules are read first as the baseline operating model.
        OutputFirstVerificationSection has Priority.CRITICAL (= 1). The fast-mode
        section must also be 1 so it tie-breaks before (added first in the
        coordination builder) or shares the same tier."""
        from massgen.system_prompt_sections import FastModeGuidanceSection

        section = FastModeGuidanceSection(
            max_verifications_per_round=1,
            max_internal_fix_loops=0,
            skip_redundant_scaffolding=False,
            scaffolding_exists=False,
        )
        # Priority enum value 1 == CRITICAL
        from massgen.system_prompt_sections import Priority

        assert section.priority == Priority.CRITICAL or section.priority == 1


# ---------------------------------------------------------------------------
# SystemMessageBuilder integration tests
# ---------------------------------------------------------------------------


class _DummyBackend:
    def __init__(self):
        self.config = {"model": "gpt-4o-mini"}
        self.filesystem_manager = None


class _DummyAgent:
    def __init__(self, system_message: str = "You are Agent A."):
        self.backend = _DummyBackend()
        self._system_message = system_message

    def get_configurable_system_message(self):
        return self._system_message


def _build_message_builder(coord_overrides: dict | None = None):
    from massgen.agent_config import AgentConfig
    from massgen.message_templates import MessageTemplates
    from massgen.system_message_builder import SystemMessageBuilder

    config = AgentConfig.create_openai_config()
    if coord_overrides:
        for key, value in coord_overrides.items():
            setattr(config.coordination_config, key, value)
    return SystemMessageBuilder(
        config=config,
        message_templates=MessageTemplates(),
        agents={},
    )


class TestFastModeSectionInCoordinationMessage:
    def test_section_absent_when_knobs_off(self):
        builder = _build_message_builder()
        msg = builder.build_coordination_message(
            agent=_DummyAgent(),
            agent_id="agent_a",
            answers={},
            planning_mode_enabled=False,
            use_skills=False,
            enable_memory=False,
            enable_task_planning=False,
            previous_turns=[],
            vote_only=False,
            human_qa_history=None,
            agent_mapping=None,
            voting_sensitivity_override=None,
        )
        assert "Verification budget" not in msg
        assert "fix broken, defer imperfect" not in msg.lower()
        assert "no fix loops" not in msg.lower()

    def test_section_present_when_verification_cap_set(self):
        builder = _build_message_builder({"max_verifications_per_round": 1})
        msg = builder.build_coordination_message(
            agent=_DummyAgent(),
            agent_id="agent_a",
            answers={},
            planning_mode_enabled=False,
            use_skills=False,
            enable_memory=False,
            enable_task_planning=False,
            previous_turns=[],
            vote_only=False,
            human_qa_history=None,
            agent_mapping=None,
            voting_sensitivity_override=None,
        )
        assert "PHASE 1" in msg and "PHASE 2" in msg and "PHASE 3" in msg

    def test_section_present_when_fix_loops_zero(self):
        builder = _build_message_builder({"max_internal_fix_loops": 0})
        msg = builder.build_coordination_message(
            agent=_DummyAgent(),
            agent_id="agent_a",
            answers={},
            planning_mode_enabled=False,
            use_skills=False,
            enable_memory=False,
            enable_task_planning=False,
            previous_turns=[],
            vote_only=False,
            human_qa_history=None,
            agent_mapping=None,
            voting_sensitivity_override=None,
        )
        assert "no fix loops" in msg.lower()

    def test_section_present_when_full_fast_preset_active(self):
        builder = _build_message_builder(
            {
                "max_verifications_per_round": 1,
                "max_internal_fix_loops": 0,
                "skip_redundant_scaffolding": True,
            },
        )
        msg = builder.build_coordination_message(
            agent=_DummyAgent(),
            agent_id="agent_a",
            answers={},
            planning_mode_enabled=False,
            use_skills=False,
            enable_memory=False,
            enable_task_planning=False,
            previous_turns=[],
            vote_only=False,
            human_qa_history=None,
            agent_mapping=None,
            voting_sensitivity_override=None,
        )
        assert "PHASE 1" in msg and "PHASE 2" in msg and "PHASE 3" in msg
        assert "no fix loops" in msg.lower()
        # scaffolding_exists=False (no filesystem_manager) so the cached-scaffolding
        # hint should NOT appear
        assert "already exist" not in msg.lower()
        # Principle header must appear at least once
        assert "fix broken, defer imperfect" in msg.lower()
