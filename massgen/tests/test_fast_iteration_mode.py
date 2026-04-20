"""Tests for fast_iteration_mode configuration and system prompt changes.

Tests cover:
- CoordinationConfig.fast_iteration_mode field defaults
- CLI parsing of fast_iteration_mode from YAML
- System prompt changes when fast_iteration_mode is enabled:
  - Phase 4 (subagent spawning for plateaued criteria) is skipped
  - Substantiveness Test is replaced with Quick Impact Check
  - "Obviously and substantially better" is replaced with fast-mode guidance
  - Known Gaps guidance is added
  - Phase 1, 2, diagnostic analysis remain full depth
  - Verification replay and essential files manifest are kept
"""

from massgen.agent_config import CoordinationConfig
from massgen.system_prompt_sections import (
    DecompositionSection,
    EvaluationSection,
    OutputFirstVerificationSection,
    _build_checklist_gated_decision,
)

# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestCoordinationConfigFastIterationMode:
    """Tests for fast_iteration_mode in CoordinationConfig."""

    def test_defaults_to_false(self):
        """fast_iteration_mode defaults to False."""
        config = CoordinationConfig()
        assert config.fast_iteration_mode is False

    def test_can_set_to_true(self):
        """fast_iteration_mode can be set to True."""
        config = CoordinationConfig(fast_iteration_mode=True)
        assert config.fast_iteration_mode is True

    def test_can_set_to_false(self):
        """fast_iteration_mode can be explicitly set to False."""
        config = CoordinationConfig(fast_iteration_mode=False)
        assert config.fast_iteration_mode is False


class TestCLIParseFastIterationMode:
    """Tests for parsing fast_iteration_mode from YAML config dict."""

    def test_parse_fast_iteration_mode_true(self):
        """fast_iteration_mode: true is parsed from YAML."""
        from massgen.cli import _parse_coordination_config

        coord_cfg = {"fast_iteration_mode": True}
        config = _parse_coordination_config(coord_cfg)
        assert config.fast_iteration_mode is True

    def test_parse_fast_iteration_mode_false(self):
        """fast_iteration_mode: false is parsed from YAML."""
        from massgen.cli import _parse_coordination_config

        coord_cfg = {"fast_iteration_mode": False}
        config = _parse_coordination_config(coord_cfg)
        assert config.fast_iteration_mode is False

    def test_parse_fast_iteration_mode_absent(self):
        """Missing fast_iteration_mode defaults to False."""
        from massgen.cli import _parse_coordination_config

        coord_cfg = {}
        config = _parse_coordination_config(coord_cfg)
        assert config.fast_iteration_mode is False


# ---------------------------------------------------------------------------
# System prompt tests
# ---------------------------------------------------------------------------


class TestFastIterationModePromptChanges:
    """Tests for system prompt changes when fast_iteration_mode is enabled."""

    def test_normal_mode_has_phase_4_subagent_spawning(self):
        """Normal mode includes Phase 4 subagent spawning for plateaued criteria."""
        decision = _build_checklist_gated_decision(
            ["Criterion 1", "Criterion 2"],
            fast_iteration_mode=False,
        )
        assert "Phase 4" in decision
        assert "quality_rethinking" in decision or "plateaued" in decision

    def test_fast_mode_skips_phase_4_subagent_spawning(self):
        """Fast mode skips Phase 4 (subagent spawning for plateaued criteria)."""
        decision = _build_checklist_gated_decision(
            ["Criterion 1", "Criterion 2"],
            fast_iteration_mode=True,
        )
        # Phase 4 about spawning subagents for plateaued criteria should not appear
        assert "quality_rethinking" not in decision
        assert "novelty subagent" not in decision

    def test_normal_mode_has_scoring_calibration(self):
        """Normal mode includes Scoring Calibration (replaced Substantiveness Test)."""
        decision = _build_checklist_gated_decision(
            ["Criterion 1", "Criterion 2"],
            fast_iteration_mode=False,
        )
        assert "Scoring Calibration" in decision
        assert "much better" in decision

    def test_fast_mode_has_quick_impact_check(self):
        """Fast mode replaces Substantiveness Test with Quick Impact Check."""
        decision = _build_checklist_gated_decision(
            ["Criterion 1", "Criterion 2"],
            fast_iteration_mode=True,
        )
        assert "Quick Impact Check" in decision
        # Should not have the full substantiveness classification
        assert "TRANSFORMATIVE" not in decision
        assert "INCREMENTAL" not in decision

    def test_normal_mode_has_obviously_substantially_better(self):
        """Normal mode includes 'obviously and substantially better'."""
        decision = _build_checklist_gated_decision(
            ["Criterion 1", "Criterion 2"],
            fast_iteration_mode=False,
        )
        assert "obviously and substantially better" in decision

    def test_fast_mode_replaces_obviously_substantially_better(self):
        """Fast mode replaces 'obviously and substantially better' with fast-mode guidance."""
        decision = _build_checklist_gated_decision(
            ["Criterion 1", "Criterion 2"],
            fast_iteration_mode=True,
        )
        assert "obviously and substantially better" not in decision
        assert "Known Gaps" in decision

    def test_fast_mode_includes_known_gaps_guidance(self):
        """Fast mode includes Known Gaps guidance for agents."""
        decision = _build_checklist_gated_decision(
            ["Criterion 1", "Criterion 2"],
            fast_iteration_mode=True,
        )
        assert "Known Gaps" in decision

    def test_fast_mode_keeps_phase_1_evidence_gathering(self):
        """Fast mode keeps Phase 1 evidence gathering at full depth."""
        decision = _build_checklist_gated_decision(
            ["Criterion 1", "Criterion 2"],
            fast_iteration_mode=True,
        )
        assert "Phase 1" in decision
        assert "Gather evidence" in decision or "BEFORE calling" in decision

    def test_fast_mode_keeps_phase_2_scoring(self):
        """Fast mode keeps Phase 2 scoring at full depth."""
        decision = _build_checklist_gated_decision(
            ["Criterion 1", "Criterion 2"],
            fast_iteration_mode=True,
        )
        assert "Phase 2" in decision or "submit_checklist" in decision

    def test_fast_mode_keeps_verification_replay(self):
        """Fast mode keeps verification replay memo instructions."""
        decision = _build_checklist_gated_decision(
            ["Criterion 1", "Criterion 2"],
            fast_iteration_mode=True,
        )
        assert "verification" in decision.lower()

    def test_fast_mode_keeps_essential_files_manifest(self):
        """Fast mode keeps essential files manifest instructions."""
        decision = _build_checklist_gated_decision(
            ["Criterion 1", "Criterion 2"],
            fast_iteration_mode=True,
        )
        assert "essential_files_manifest" in decision

    def test_fast_mode_confidence_assessment_targets_greatness(self):
        """Fast mode confidence assessment still targets excellence across rounds."""
        decision = _build_checklist_gated_decision(
            ["Criterion 1", "Criterion 2"],
            fast_iteration_mode=True,
        )
        # Should not have the "excellence within this round" pressure
        # but should still have quality-oriented language
        assert "excellence" not in decision or "across rounds" in decision

    def test_evaluation_section_passes_fast_iteration_mode(self):
        """EvaluationSection accepts and threads fast_iteration_mode parameter."""
        section = EvaluationSection(
            voting_sensitivity="checklist_gated",
            fast_iteration_mode=True,
        )
        assert section.fast_iteration_mode is True

    def test_evaluation_section_default_fast_iteration_mode(self):
        """EvaluationSection defaults fast_iteration_mode to False."""
        section = EvaluationSection(
            voting_sensitivity="checklist_gated",
        )
        assert section.fast_iteration_mode is False

    def test_evaluation_section_build_content_fast_mode(self):
        """EvaluationSection.build_content() includes fast mode changes when enabled."""
        section = EvaluationSection(
            voting_sensitivity="checklist_gated",
            fast_iteration_mode=True,
            custom_checklist_items=["Quality is high", "Requirements are met"],
        )
        content = section.build_content()
        assert "Quick Impact Check" in content
        assert "Known Gaps" in content

    def test_evaluation_section_build_content_normal_mode(self):
        """EvaluationSection.build_content() uses normal text when fast_iteration_mode is False."""
        section = EvaluationSection(
            voting_sensitivity="checklist_gated",
            fast_iteration_mode=False,
            custom_checklist_items=["Quality is high", "Requirements are met"],
        )
        content = section.build_content()
        assert "Scoring Calibration" in content

    def test_fast_mode_full_section_no_obviously_substantially_better(self):
        """Full EvaluationSection output must not contain 'obviously and substantially better' in fast mode.

        This tests the common return block wrapper, not just the decision function.
        """
        section = EvaluationSection(
            voting_sensitivity="checklist_gated",
            fast_iteration_mode=True,
            custom_checklist_items=["Quality is high", "Requirements are met"],
        )
        content = section.build_content()
        assert "obviously and substantially better" not in content
        # Should have the fast-mode iteration guidance instead
        assert "let the system iterate" in content

    def test_fast_mode_phase_reference_correct(self):
        """Fast mode should reference Phase 4 (not Phase 5) for terminate action."""
        decision = _build_checklist_gated_decision(
            ["Criterion 1", "Criterion 2"],
            fast_iteration_mode=True,
        )
        assert "skip to Phase 4" in decision
        assert "skip to Phase 5" not in decision

    def test_normal_mode_phase_reference_correct(self):
        """Normal mode should reference Phase 5 for terminate action."""
        decision = _build_checklist_gated_decision(
            ["Criterion 1", "Criterion 2"],
            fast_iteration_mode=False,
        )
        assert "skip to Phase 5" in decision


# ---------------------------------------------------------------------------
# Pre-collab threading tests
# ---------------------------------------------------------------------------


class TestFastIterationModePreCollabThreading:
    """Tests that fast_iteration_mode is threaded to pre-collab generators."""

    def test_persona_generator_accepts_fast_iteration_mode(self):
        """PersonaGenerator.generate_personas_via_subagent accepts fast_iteration_mode."""
        import inspect

        from massgen.persona_generator import PersonaGenerator

        sig = inspect.signature(PersonaGenerator.generate_personas_via_subagent)
        assert "fast_iteration_mode" in sig.parameters

    def test_evaluation_criteria_generator_accepts_fast_iteration_mode(self):
        """EvaluationCriteriaGenerator.generate_criteria_via_subagent accepts fast_iteration_mode."""
        import inspect

        from massgen.evaluation_criteria_generator import EvaluationCriteriaGenerator

        sig = inspect.signature(EvaluationCriteriaGenerator.generate_criteria_via_subagent)
        assert "fast_iteration_mode" in sig.parameters

    def test_task_decomposer_accepts_fast_iteration_mode(self):
        """TaskDecomposer.generate_decomposition_via_subagent accepts fast_iteration_mode."""
        import inspect

        from massgen.task_decomposer import TaskDecomposer

        sig = inspect.signature(TaskDecomposer.generate_decomposition_via_subagent)
        assert "fast_iteration_mode" in sig.parameters

    def test_prompt_improver_accepts_fast_iteration_mode(self):
        """PromptImprover.improve_prompt_via_subagent accepts fast_iteration_mode."""
        import inspect

        from massgen.prompt_improver import PromptImprover

        sig = inspect.signature(PromptImprover.improve_prompt_via_subagent)
        assert "fast_iteration_mode" in sig.parameters


# ---------------------------------------------------------------------------
# DecompositionSection tests
# ---------------------------------------------------------------------------


class TestFastIterationModeDecompositionSection:
    """Tests that DecompositionSection threads fast_iteration_mode."""

    def test_decomposition_section_accepts_fast_iteration_mode(self):
        """DecompositionSection accepts fast_iteration_mode parameter."""
        section = DecompositionSection(
            subtask="Build the frontend",
            voting_sensitivity="checklist_gated",
            fast_iteration_mode=True,
        )
        assert section.fast_iteration_mode is True

    def test_decomposition_section_defaults_fast_iteration_mode(self):
        """DecompositionSection defaults fast_iteration_mode to False."""
        section = DecompositionSection(subtask="Build the frontend")
        assert section.fast_iteration_mode is False

    def test_decomposition_checklist_gated_fast_mode(self):
        """DecompositionSection with checklist_gated passes fast mode to decision."""
        section = DecompositionSection(
            subtask="Build the frontend",
            voting_sensitivity="checklist_gated",
            voting_threshold=70,
            fast_iteration_mode=True,
            custom_checklist_items=["Quality is high", "Requirements met"],
        )
        content = section.build_content()
        assert "Quick Impact Check" in content
        assert "Known Gaps" in content

    def test_decomposition_checklist_gated_normal_mode(self):
        """DecompositionSection with checklist_gated uses normal text when fast mode off."""
        section = DecompositionSection(
            subtask="Build the frontend",
            voting_sensitivity="checklist_gated",
            voting_threshold=70,
            fast_iteration_mode=False,
            custom_checklist_items=["Quality is high", "Requirements met"],
        )
        content = section.build_content()
        assert "Scoring Calibration" in content


# ---------------------------------------------------------------------------
# to_dict roundtrip test
# ---------------------------------------------------------------------------


class TestFastIterationModeSerialization:
    """Tests for fast_iteration_mode serialization."""

    def test_to_dict_includes_fast_iteration_mode(self):
        """AgentConfig.to_dict() includes fast_iteration_mode."""
        from massgen.agent_config import AgentConfig

        config = AgentConfig(
            coordination_config=CoordinationConfig(fast_iteration_mode=True),
        )
        d = config.to_dict()
        assert d["coordination_config"]["fast_iteration_mode"] is True

    def test_to_dict_includes_fast_iteration_mode_false(self):
        """AgentConfig.to_dict() includes fast_iteration_mode when False."""
        from massgen.agent_config import AgentConfig

        config = AgentConfig(
            coordination_config=CoordinationConfig(fast_iteration_mode=False),
        )
        d = config.to_dict()
        assert d["coordination_config"]["fast_iteration_mode"] is False


# ---------------------------------------------------------------------------
# Config validator test
# ---------------------------------------------------------------------------


class TestFastIterationModeValidation:
    """Tests for config validator handling of fast_iteration_mode."""

    def test_valid_fast_iteration_mode(self):
        """Config with fast_iteration_mode: true passes validation."""
        from massgen.config_validator import ConfigValidator

        config = {
            "agents": [
                {"id": "a1", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "coordination": {"fast_iteration_mode": True},
            },
        }
        result = ConfigValidator().validate_config(config)
        assert result.is_valid()

    def test_invalid_fast_iteration_mode_type(self):
        """Config with non-boolean fast_iteration_mode fails validation."""
        from massgen.config_validator import ConfigValidator

        config = {
            "agents": [
                {"id": "a1", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "coordination": {"fast_iteration_mode": "yes"},
            },
        }
        result = ConfigValidator().validate_config(config)
        assert result.has_errors()


# ---------------------------------------------------------------------------
# OutputFirstVerificationSection tests
# ---------------------------------------------------------------------------


class TestFastIterationModeOutputFirstSection:
    """Tests that OutputFirstVerificationSection respects fast_iteration_mode."""

    def test_normal_mode_has_improvement_loop(self):
        """Normal mode includes the full improvement loop."""
        section = OutputFirstVerificationSection(fast_iteration_mode=False)
        content = section.build_content()
        assert "improvement loop" in content
        assert "Submit when excellent" in content

    def test_fast_mode_removes_improvement_loop(self):
        """Fast mode replaces the improvement loop with the three-phase lifecycle."""
        section = OutputFirstVerificationSection(fast_iteration_mode=True)
        content = section.build_content()
        assert "improvement loop" not in content
        assert "Submit when excellent" not in content
        # Either 'Known Gap' or 'Known Gaps' suffices under the phase model
        assert "Known Gap" in content

    def test_fast_mode_keeps_verification_guidance(self):
        """Fast mode still includes dynamic verification guidance."""
        section = OutputFirstVerificationSection(fast_iteration_mode=True)
        content = section.build_content()
        assert "Dynamic Verification" in content
        assert "User Experience Test" in content

    def test_fast_mode_has_no_loop_instruction(self):
        """Fast mode forbids in-round loops — either directly ('Do not loop')
        or structurally via the PHASE 2 no-verification rule."""
        section = OutputFirstVerificationSection(fast_iteration_mode=True)
        content = section.build_content()
        # The phase model carries the no-loop discipline structurally:
        # PHASE 2 forbids verification, so no verify→edit→verify cycle is possible.
        assert "Do not loop" in content or ("PHASE 2" in content and "no verification" in content.lower())
