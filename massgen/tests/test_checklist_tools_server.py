#!/usr/bin/env python3
"""Unit tests for the checklist MCP tools server.

Tests cover:
- _extract_score() from different input types
- submit_checklist verdict logic (iterate vs terminate)
- First-answer forced iterate behavior
- Codex JSON-string normalization for scores
- Per-criterion plateau detection
- draft_approach validation
- write_checklist_specs() file I/O
- build_server_config() structure
"""

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from massgen.mcp_tools.checklist_tools_server import (
    _extract_score,
    _find_plateaued_criteria,
    _read_specs,
    _resolve_report_file,
    build_server_config,
    evaluate_checklist_submission,
    evaluate_draft_approach,
    write_checklist_specs,
)

# ---------------------------------------------------------------------------
# _extract_score
# ---------------------------------------------------------------------------


class TestExtractScore:
    """Tests for _extract_score helper."""

    def test_int_value(self):
        assert _extract_score(80) == 80

    def test_float_value(self):
        assert _extract_score(75.9) == 75

    def test_dict_with_score(self):
        assert _extract_score({"score": 90, "reasoning": "great"}) == 90

    def test_dict_missing_score_key(self):
        assert _extract_score({"reasoning": "no score"}) == 0

    def test_string_returns_zero(self):
        assert _extract_score("not a number") == 0

    def test_none_returns_zero(self):
        assert _extract_score(None) == 0

    def test_zero_score(self):
        assert _extract_score(0) == 0

    def test_dict_with_zero_score(self):
        assert _extract_score({"score": 0, "reasoning": "failed"}) == 0


# ---------------------------------------------------------------------------
# _read_specs
# ---------------------------------------------------------------------------


class TestReadSpecs:
    """Tests for _read_specs file reader."""

    def test_reads_valid_json(self, tmp_path):
        specs_file = tmp_path / "specs.json"
        specs_file.write_text(json.dumps({"items": ["a", "b"], "state": {}}))
        result = _read_specs(specs_file)
        assert result["items"] == ["a", "b"]

    def test_returns_empty_on_missing_file(self, tmp_path):
        result = _read_specs(tmp_path / "missing.json")
        assert result == {}

    def test_returns_empty_on_invalid_json(self, tmp_path):
        specs_file = tmp_path / "bad.json"
        specs_file.write_text("not json")
        result = _read_specs(specs_file)
        assert result == {}


# ---------------------------------------------------------------------------
# submit_checklist handler (tested via direct function invocation)
# ---------------------------------------------------------------------------


def _make_specs_file(tmp_path, items, state):
    """Helper to write a checklist specs file and return its path."""
    specs_path = tmp_path / "specs.json"
    write_checklist_specs(items, state, specs_path)
    return specs_path


def _build_handler(specs_path):
    """Build the submit_checklist handler by extracting it from registration."""
    return _build_handlers(specs_path)["submit_checklist"]


def _build_handlers(specs_path):
    """Build checklist tool handlers keyed by tool name."""
    import fastmcp

    mcp = fastmcp.FastMCP("test_checklist")
    from massgen.mcp_tools.checklist_tools_server import _register_checklist_tool

    _register_checklist_tool(mcp, specs_path)

    handlers = {}
    for tool in mcp._tool_manager._tools.values():
        handlers[tool.name] = tool.fn
    if "submit_checklist" not in handlers:
        raise RuntimeError("submit_checklist tool not found after registration")
    return handlers


class TestSubmitChecklistVerdict:
    """Tests for the submit_checklist tool's verdict logic."""

    @pytest.mark.asyncio
    async def test_all_pass_returns_terminate(self, tmp_path):
        """When all items pass the cutoff, verdict should be terminate action."""
        items = ["Quality check 1", "Quality check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "require_gap_report": False,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 7, "reasoning": "ok"}},
            ),
        )
        assert result["verdict"] == "vote"
        assert result["true_count"] == 2

    @pytest.mark.asyncio
    async def test_partial_pass_returns_iterate(self, tmp_path):
        """When not enough items pass, verdict should be iterate action."""
        items = ["Check 1", "Check 2", "Check 3"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 3,
            "cutoff": 7,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 5, "reasoning": "bad"}, "E3": {"score": 9, "reasoning": "great"}},
            ),
        )
        assert result["verdict"] == "new_answer"
        assert result["true_count"] == 2
        assert "E2" in result["explanation"]

    @pytest.mark.asyncio
    async def test_first_answer_forces_iterate(self, tmp_path):
        """When has_existing_answers is False, verdict must always iterate."""
        items = ["Check 1"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": False,
            "required": 1,
            "cutoff": 7,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={"E1": {"score": 10, "reasoning": "perfect"}},
            ),
        )
        # Even though score passes, first answer always iterates
        assert result["verdict"] == "new_answer"
        assert "First answer" in result["explanation"]

    @pytest.mark.asyncio
    async def test_codex_json_string_scores(self, tmp_path):
        """Codex sends scores as JSON string; handler should normalize."""
        items = ["Check 1"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 1,
            "cutoff": 7,
            "require_gap_report": False,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        # Send scores as a JSON string (Codex behavior)
        result = json.loads(
            await handler(
                scores='{"E1": {"score": 8, "reasoning": "good"}}',
            ),
        )
        assert result["verdict"] == "vote"
        assert result["true_count"] == 1

    @pytest.mark.asyncio
    async def test_invalid_json_string_returns_error(self, tmp_path):
        """Invalid JSON string for scores should return an error."""
        items = ["Check 1"]
        state = {"has_existing_answers": True, "required": 1, "cutoff": 7}
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(await handler(scores="not valid json"))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_missing_score_keys_rejected_when_existing_answers(self, tmp_path):
        """Missing score entries should be rejected with incomplete_scores flag."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        # Only provide E1, E2 is missing
        result = json.loads(
            await handler(
                scores={"E1": {"score": 8, "reasoning": "good"}},
            ),
        )
        assert result["status"] == "validation_error"
        assert result["requires_resubmission"] is True
        assert result["incomplete_scores"] is True
        assert "verdict" not in result
        assert "E2" in result["explanation"]

    @pytest.mark.asyncio
    async def test_missing_score_keys_default_to_zero_on_first_answer(self, tmp_path):
        """Missing score entries should default to 0 on first answer (no rejection)."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": False,
            "required": 2,
            "cutoff": 7,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        # Only provide E1, E2 is missing — first answer, so no rejection
        result = json.loads(
            await handler(
                scores={"E1": {"score": 8, "reasoning": "good"}},
            ),
        )
        assert result["verdict"] == "new_answer"
        assert result.get("incomplete_scores") is not True

    @pytest.mark.asyncio
    async def test_custom_terminate_and_iterate_actions(self, tmp_path):
        """Custom action names (stop/continue) should be used in verdicts."""
        items = ["Check 1"]
        state = {
            "terminate_action": "stop",
            "iterate_action": "continue",
            "has_existing_answers": True,
            "required": 1,
            "cutoff": 7,
            "require_gap_report": False,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={"E1": {"score": 8, "reasoning": "good"}},
            ),
        )
        assert result["verdict"] == "stop"

    @pytest.mark.asyncio
    async def test_decomposition_mode_accepts_flat_scores_with_multiple_agents(self, tmp_path):
        """Decomposition mode should score the current subtask output, not require per-agent ranking."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "stop",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "require_gap_report": False,
            "decomposition_mode": True,
            "current_answer_label": "agent1.2",
            "available_agent_labels": ["agent1.2", "agent2.1"],
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={
                    "E1": {"score": 8, "reasoning": "subtask work is solid"},
                    "E2": {"score": 8, "reasoning": "integration points are covered"},
                },
            ),
        )

        assert result["status"] == "accepted"
        assert result["verdict"] == "stop"


# ---------------------------------------------------------------------------
# Incomplete score rejection
# ---------------------------------------------------------------------------


class TestIncompleteScoreRejection:
    """Tests for incomplete score submission rejection."""

    def test_missing_scores_rejected_with_existing_answers(self):
        """Incomplete submissions with existing answers should be rejected."""
        items = ["Check 1", "Check 2", "Check 3"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 3,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={"E1": {"score": 8, "reasoning": "good"}},
            report_path="",
            items=items,
            state=state,
        )
        assert result["status"] == "validation_error"
        assert result["requires_resubmission"] is True
        assert result["incomplete_scores"] is True
        assert "verdict" not in result
        assert "E2" in result["explanation"]
        assert "E3" in result["explanation"]

    def test_complete_submission_not_rejected(self):
        """Complete submissions should proceed normally."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 8, "reasoning": "good"},
                "E2": {"score": 9, "reasoning": "great"},
            },
            report_path="",
            items=items,
            state=state,
        )
        assert result["verdict"] == "vote"
        assert result.get("incomplete_scores") is not True

    def test_empty_scores_rejected(self):
        """Empty scores dict should be rejected when existing answers present."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={},
            report_path="",
            items=items,
            state=state,
        )
        assert result["status"] == "validation_error"
        assert result["requires_resubmission"] is True
        assert result["incomplete_scores"] is True
        assert "verdict" not in result

    def test_first_answer_not_rejected_for_missing_scores(self):
        """First answer (no existing answers) should not be rejected for missing scores."""
        items = ["Check 1", "Check 2", "Check 3"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": False,
            "required": 3,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={"E1": {"score": 8, "reasoning": "good"}},
            report_path="",
            items=items,
            state=state,
        )
        # First answer always iterates, but NOT because of incomplete scores
        assert result["verdict"] == "new_answer"
        assert result.get("incomplete_scores") is not True

    def test_t_prefix_accepted_for_backward_compat(self):
        """T-prefix keys should be accepted as equivalent to E-prefix."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={
                "T1": {"score": 8, "reasoning": "good"},
                "T2": {"score": 9, "reasoning": "great"},
            },
            report_path="",
            items=items,
            state=state,
        )
        assert result["verdict"] == "vote"
        assert result.get("incomplete_scores") is not True

    def test_rejection_message_includes_all_missing_keys(self):
        """Rejection message should list all missing keys."""
        items = ["A", "B", "C", "D", "E"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 5,
            "cutoff": 7,
        }
        # Only E1 and E3 provided, missing E2, E4, E5
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 8, "reasoning": "ok"},
                "E3": {"score": 7, "reasoning": "ok"},
            },
            report_path="",
            items=items,
            state=state,
        )
        assert result["incomplete_scores"] is True
        assert "E2" in result["explanation"]
        assert "E4" in result["explanation"]
        assert "E5" in result["explanation"]


# ---------------------------------------------------------------------------
# write_checklist_specs & build_server_config
# ---------------------------------------------------------------------------


class TestWriteChecklistSpecs:
    """Tests for write_checklist_specs utility."""

    def test_writes_valid_json(self, tmp_path):
        items = ["Item 1", "Item 2"]
        state = {"required": 2, "cutoff": 70}
        output = write_checklist_specs(items, state, tmp_path / "out.json")
        assert output.exists()
        data = json.loads(output.read_text())
        assert data["items"] == items
        assert data["state"] == state

    def test_creates_parent_directories(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "specs.json"
        write_checklist_specs([], {}, nested)
        assert nested.exists()


class TestGapReportGateRemoval:
    """Tests for gap report gate removal — verdict determined solely by T-item scores."""

    def test_verdict_not_overridden_by_poor_report(self, tmp_path):
        """Checklist passes -> vote verdict, regardless of report quality."""
        items = ["Quality check 1", "Quality check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        # All scores pass, no report path — verdict should be "vote"
        result = evaluate_checklist_submission(
            scores={"E1": 8, "E2": 9},
            report_path="",
            items=items,
            state=state,
        )
        assert result["verdict"] == "vote"
        # Report gate should NOT override
        assert result.get("report_gate_triggered") is False

    def test_report_diagnostics_still_in_result(self, tmp_path):
        """Gap report diagnostics are included in result dict for transparency."""
        items = ["Quality check 1"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 1,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={"E1": 8},
            report_path="",
            items=items,
            state=state,
        )
        # Report diagnostics should be in the result
        assert "report" in result
        assert isinstance(result["report"], dict)

    def test_report_path_optional(self):
        """No crash when report_path is empty or absent."""
        items = ["Check 1"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 1,
            "cutoff": 7,
        }
        # Empty report path
        result = evaluate_checklist_submission(
            scores={"E1": 9},
            report_path="",
            items=items,
            state=state,
        )
        assert result["verdict"] == "vote"

        # None-ish report path
        result2 = evaluate_checklist_submission(
            scores={"E1": 9},
            report_path="nonexistent/path.md",
            items=items,
            state=state,
        )
        assert result2["verdict"] == "vote"


class TestChecklistRequiredTrue:
    """Tests for _checklist_required_true relaxation on the 0-10 effective-threshold scale.

    The effective threshold is produced by _checklist_effective_threshold and is
    always clamped to [0, 10]; the relaxation must therefore activate within that
    range (the previous `// 30` formula made relaxation dead under every config).
    """

    def test_threshold_0_requires_all_items(self):
        """At ET=0 (ample budget, low base threshold), every item is required."""
        from massgen.system_prompt_sections import _checklist_required_true

        assert _checklist_required_true(0) == 4
        assert _checklist_required_true(0, num_items=4) == 4
        assert _checklist_required_true(0, num_items=5) == 5
        assert _checklist_required_true(0, num_items=3) == 3

    def test_relaxation_activates_within_0_10_scale(self):
        """Relaxation must fire for ET values configs actually produce (2-7)."""
        from massgen.system_prompt_sections import _checklist_required_true

        # 4 items, floor 2: ET 3-7 relaxes to 3.
        assert _checklist_required_true(3, num_items=4) == 3
        assert _checklist_required_true(5, num_items=4) == 3
        assert _checklist_required_true(7, num_items=4) == 3

    def test_high_threshold_relaxes_to_floor(self):
        """At the top of the scale, requirement reaches (but never passes) the floor."""
        from massgen.system_prompt_sections import _checklist_required_true

        assert _checklist_required_true(8, num_items=4) == 2  # floor for 4 items
        assert _checklist_required_true(10, num_items=4) == 2
        assert _checklist_required_true(10, num_items=5) == 3  # floor for 5 items
        assert _checklist_required_true(10, num_items=3) == 2  # floor for 3 items

    def test_never_below_floor_even_above_scale(self):
        """ET beyond the 0-10 range is clamped; never drops below the majority floor."""
        from massgen.system_prompt_sections import _checklist_required_true

        assert _checklist_required_true(100, num_items=4) == 2
        assert _checklist_required_true(100, num_items=3) == 2

    def test_required_is_monotonic_non_increasing(self):
        """Higher effective threshold must never increase the required count."""
        from massgen.system_prompt_sections import _checklist_required_true

        for n in (3, 4, 5):
            seq = [_checklist_required_true(et, num_items=n) for et in range(0, 11)]
            assert all(b <= a for a, b in zip(seq, seq[1:])), (n, seq)
            assert min(seq) == max(1, (n + 1) // 2)  # bottoms out at floor


# ---------------------------------------------------------------------------
# Per-criterion plateau detection
# ---------------------------------------------------------------------------


class TestCriterionPlateau:
    """Tests for _find_plateaued_criteria helper."""

    def test_plateau_detected_after_two_flat_rounds(self):
        """Same score for 2 rounds → plateaued."""
        current_items = [{"id": "E1", "score": 5}, {"id": "E2", "score": 7}]
        history = [
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 7}]},
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 7}]},
        ]
        result = _find_plateaued_criteria(current_items, history, min_rounds=2)
        result_ids = [d["id"] for d in result]
        assert "E1" in result_ids
        assert "E2" in result_ids

    def test_no_plateau_when_improving(self):
        """Score increases → not plateaued."""
        current_items = [{"id": "E1", "score": 8}, {"id": "E2", "score": 9}]
        history = [
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 6}]},
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 6}]},
        ]
        # No items/categories needed when result is empty
        result = _find_plateaued_criteria(current_items, history, min_rounds=2)
        assert result == []

    def test_no_plateau_with_insufficient_history(self):
        """<2 rounds of history → empty."""
        current_items = [{"id": "E1", "score": 5}]
        history = [
            {"items_detail": [{"id": "E1", "score": 5}]},
        ]
        result = _find_plateaued_criteria(current_items, history, min_rounds=2)
        assert result == []

    def test_per_criterion_plateau(self):
        """E1 stuck but E2 improving → only E1 plateaued."""
        current_items = [{"id": "E1", "score": 5}, {"id": "E2", "score": 9}]
        history = [
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 6}]},
        ]
        result = _find_plateaued_criteria(current_items, history, min_rounds=2)
        result_ids = [d["id"] for d in result]
        assert "E1" in result_ids
        assert "E2" not in result_ids

    def test_plateau_threshold(self):
        """+1 point = still plateau, +2 = not plateau."""
        current_items = [{"id": "E1", "score": 6}, {"id": "E2", "score": 7}]
        history = [
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
        ]
        result = _find_plateaued_criteria(current_items, history, min_rounds=2)
        # E1: 6 > 5 + 1 is False, so E1 is stuck
        result_ids = [d["id"] for d in result]
        assert "E1" in result_ids
        # E2: 7 > 5 + 1 is True, so E2 is improving
        assert "E2" not in result_ids

    def test_returns_rich_detail_dicts(self):
        """Plateaued criteria return dicts with id, text, category, score_history, current_score."""
        items = ["First criterion text", "Second criterion text"]
        categories = {"E1": "should", "E2": "could"}
        current_items = [{"id": "E1", "score": 6}, {"id": "E2", "score": 5}]
        history = [
            {"items_detail": [{"id": "E1", "score": 6}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 6}, {"id": "E2", "score": 5}]},
        ]
        result = _find_plateaued_criteria(
            current_items,
            history,
            items=items,
            item_categories=categories,
            min_rounds=2,
        )
        assert len(result) == 2
        e1 = next(d for d in result if d["id"] == "E1")
        assert e1["text"] == "First criterion text"
        assert e1["category"] == "should"
        assert e1["current_score"] == 6
        assert "score_history" in e1

    def test_score_trajectory_in_detail(self):
        """Score history includes prior rounds + current score."""
        items = ["Criterion A"]
        categories = {"E1": "must"}
        current_items = [{"id": "E1", "score": 6}]
        history = [
            {"items_detail": [{"id": "E1", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 6}]},
        ]
        result = _find_plateaued_criteria(
            current_items,
            history,
            items=items,
            item_categories=categories,
            min_rounds=2,
        )
        assert len(result) == 1
        assert result[0]["score_history"] == [5, 6, 6]


# ---------------------------------------------------------------------------
# draft_approach validation
# ---------------------------------------------------------------------------


class TestProposeImprovements:
    """Tests for evaluate_draft_approach function."""

    # Disable impact gate for tests focused on other validation logic.
    _NO_GATE = {"improvements": {"min_transformative": 0, "min_structural": 0, "min_non_incremental": 0}}

    def test_valid_improvements_all_criteria_covered(self):
        """All failing criteria covered → valid."""
        result = evaluate_draft_approach(
            improvements={"E2": ["fix fonts"], "E5": ["add timeline"]},
            failed_criteria=["E2", "E5"],
            items=["Check 1", "Check 2", "Check 3", "Check 4", "Check 5"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True
        assert "task_plan" in result
        assert len(result["task_plan"]) == 2

    def test_missing_criteria_returns_error(self):
        """Missing improvements for a criterion → error."""
        result = evaluate_draft_approach(
            improvements={"E2": ["fix fonts"]},
            failed_criteria=["E2", "E5"],
            items=["Check 1", "Check 2", "Check 3", "Check 4", "Check 5"],
            state=self._NO_GATE,
        )
        assert result["valid"] is False
        assert "E5" in result["error"]
        assert "E5" in result["missing_criteria"]

    def test_empty_improvements_for_criterion_returns_error(self):
        """Empty list for a criterion → error."""
        result = evaluate_draft_approach(
            improvements={"E2": ["fix fonts"], "E5": []},
            failed_criteria=["E2", "E5"],
            items=["Check 1", "Check 2", "Check 3", "Check 4", "Check 5"],
            state=self._NO_GATE,
        )
        assert result["valid"] is False
        assert "E5" in result["empty_criteria"]

    def test_task_plan_built_from_improvements(self):
        """Task plan items contain criterion info and improvement text."""
        result = evaluate_draft_approach(
            improvements={
                "E1": ["add mobile nav", "fix breakpoints"],
                "E3": ["add real images"],
            },
            failed_criteria=["E1", "E3"],
            items=["Goal alignment", "Correctness", "Depth"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True
        assert len(result["task_plan"]) == 3
        # Check structure
        first = result["task_plan"][0]
        assert first["criterion_id"] == "E1"
        assert first["criterion"] == "Goal alignment"
        assert first["improvement"] == "add mobile nav"

    def test_delegate_execution_set_for_structural_impact_when_subagents_enabled(self):
        """Structural impact improvements should suggest delegated builder execution when available."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "redesign nav", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=["Check 1"],
            state={**self._NO_GATE, "subagents_enabled": True},
        )
        assert result["valid"] is True
        improve_entry = [t for t in result["task_plan"] if t["type"] == "improve"][0]
        assert improve_entry["execution"] == {"mode": "delegate", "subagent_type": "builder"}

    def test_delegate_execution_set_for_transformative_impact_when_subagents_enabled(self):
        """Transformative impact improvements should suggest delegated builder execution when available."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "switch architecture", "sources": [], "impact": "transformative"}],
            },
            failed_criteria=["E1"],
            items=["Check 1"],
            state={**self._NO_GATE, "subagents_enabled": True},
        )
        assert result["valid"] is True
        improve_entry = [t for t in result["task_plan"] if t["type"] == "improve"][0]
        assert improve_entry["execution"] == {"mode": "delegate", "subagent_type": "builder"}

    def test_no_delegate_execution_for_incremental(self):
        """Incremental impact should stay inline."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "polish spacing", "sources": [], "impact": "incremental"}],
            },
            failed_criteria=["E1"],
            items=["Check 1"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True
        improve_entry = [t for t in result["task_plan"] if t["type"] == "improve"][0]
        assert improve_entry["execution"] == {"mode": "inline"}

    def test_no_delegate_execution_for_structural_when_subagents_disabled(self):
        """Structural work should stay inline when subagents are unavailable."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "redesign nav", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=["Check 1"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True
        improve_entry = [t for t in result["task_plan"] if t["type"] == "improve"][0]
        assert improve_entry["execution"] == {"mode": "inline"}

    def test_novelty_task_injected_on_round_2_plus(self):
        """Round 2+ with novelty-on-iteration enabled should prepend novelty task."""
        state = {
            **self._NO_GATE,
            "subagents_enabled": True,
            "enable_novelty_on_iteration": True,
            "enable_quality_rethink_on_iteration": False,
            "agent_answer_count": 1,
        }
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "redesign", "sources": [], "impact": "structural"}],
                "E3": [{"plan": "recompose layout", "sources": [], "impact": "transformative"}],
            },
            failed_criteria=["E1", "E3"],
            items=["Check 1", "Check 2", "Check 3"],
            state=state,
        )
        assert result["valid"] is True
        assert result["task_plan"][0]["type"] == "novelty_quality_spawn"
        assert result["task_plan"][0]["metadata"]["failing_criteria"] == ["E1", "E3"]
        assert result["task_plan"][0]["metadata"]["spawn_novelty"] is True
        assert result["task_plan"][0]["metadata"]["spawn_quality_rethinking"] is False

    def test_quality_rethinking_task_injected_on_round_2_plus(self):
        """Round 2+ with quality-on-iteration enabled should prepend spawn task."""
        state = {
            **self._NO_GATE,
            "subagents_enabled": True,
            "enable_novelty_on_iteration": False,
            "enable_quality_rethink_on_iteration": True,
            "agent_answer_count": 1,
        }
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "redesign", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=["Check 1"],
            state=state,
        )
        assert result["valid"] is True
        assert result["task_plan"][0]["type"] == "novelty_quality_spawn"
        assert result["task_plan"][0]["metadata"]["spawn_novelty"] is False
        assert result["task_plan"][0]["metadata"]["spawn_quality_rethinking"] is True

    def test_novelty_spawn_includes_verbatim_evaluation_packet_and_templates(self):
        """Spawn task should carry exact evaluation packet plus copy-ready task templates."""
        state = {
            **self._NO_GATE,
            "subagents_enabled": True,
            "enable_novelty_on_iteration": True,
            "enable_quality_rethink_on_iteration": True,
            "agent_answer_count": 1,
        }
        latest_evaluation = {
            "failed_criteria": ["E1", "E2"],
            "failing_criteria_detail": [
                {
                    "id": "E1",
                    "text": "Hero clarity",
                    "category": "must",
                    "current_score": 5,
                },
            ],
            "plateaued_criteria": [
                {
                    "id": "E1",
                    "text": "Hero clarity",
                    "category": "must",
                    "score_history": [5, 5, 5],
                    "current_score": 5,
                },
            ],
            "checklist_explanation": "E1 plateaued and E2 still weak.",
            "diagnostic_report_path": "/tmp/report.md",
            "diagnostic_report_artifact_paths": [
                "/tmp/screenshots/hero.png",
                "/tmp/screenshots/cta.png",
            ],
        }
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "redesign hero", "sources": [], "impact": "structural"}],
                "E2": [{"plan": "rewrite CTA", "sources": [], "impact": "transformative"}],
            },
            failed_criteria=["E1", "E2"],
            items=["Hero clarity", "CTA clarity"],
            state=state,
            latest_evaluation=latest_evaluation,
        )
        assert result["valid"] is True
        spawn_task = result["task_plan"][0]
        assert spawn_task["type"] == "novelty_quality_spawn"
        metadata = spawn_task["metadata"]
        assert metadata["evaluation_input"]["failed_criteria"] == ["E1", "E2"]
        assert metadata["evaluation_input"]["plateaued_criteria"][0]["score_history"] == [5, 5, 5]
        assert metadata["evaluation_input"]["diagnostic_report_path"] == "/tmp/report.md"
        assert metadata["evaluation_input"]["diagnostic_report_artifact_paths"] == [
            "/tmp/screenshots/hero.png",
            "/tmp/screenshots/cta.png",
        ]
        assert "subagent_task_templates" in metadata
        novelty_template = metadata["subagent_task_templates"]["novelty_task_template"]
        quality_template = metadata["subagent_task_templates"]["quality_rethinking_task_template"]
        assert "Evaluation Input (verbatim)" in novelty_template
        assert "Evaluation Input (verbatim)" in quality_template
        assert "Do NOT re-evaluate" in novelty_template
        assert "Do NOT re-evaluate" in quality_template

    def test_no_novelty_task_on_round_1(self):
        """Round 1 should not inject novelty task even when novelty-on-iteration is enabled."""
        state = {
            **self._NO_GATE,
            "subagents_enabled": True,
            "enable_novelty_on_iteration": True,
            "enable_quality_rethink_on_iteration": True,
            "agent_answer_count": 0,
        }
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "redesign", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=["Check 1"],
            state=state,
        )
        assert result["valid"] is True
        assert all(task["type"] != "novelty_quality_spawn" for task in result["task_plan"])

    def test_improvements_must_be_dict(self):
        """Non-dict improvements → error."""
        result = evaluate_draft_approach(
            improvements="just a string",
            failed_criteria=["E1"],
            items=["Check 1"],
        )
        assert result["valid"] is False
        assert "must be a dict" in result["error"]

    # --- Structured improvements (plan + sources) ---

    def test_structured_improvements_accepted(self):
        """Structured [{"plan": "...", "sources": [...]}] format accepted."""
        result = evaluate_draft_approach(
            improvements={
                "E2": [{"plan": "rethink feature cards", "sources": ["agent_b.1"]}],
            },
            failed_criteria=["E2"],
            items=["Check 1", "Check 2"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True

    def test_string_improvements_backward_compat(self):
        """Plain string lists auto-wrapped to {"plan": str, "sources": [], "impact": "incremental"}."""
        result = evaluate_draft_approach(
            improvements={"E1": ["fix layout"]},
            failed_criteria=["E1"],
            items=["Check 1"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True
        improve_entries = [t for t in result["task_plan"] if t.get("type", "improve") == "improve"]
        assert len(improve_entries) >= 1
        # Should have plan and sources in task_plan entry
        assert improve_entries[0]["plan"] == "fix layout"
        assert improve_entries[0]["sources"] == []

    # --- Preserve parameter ---

    def test_preserve_required_when_criteria_exist(self):
        """Empty preserve + all_criteria_ids provided → error."""
        result = evaluate_draft_approach(
            improvements={"E2": [{"plan": "fix layout", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2", "Check 3"],
            all_criteria_ids=["E1", "E2", "E3"],
            preserve={},
        )
        assert result["valid"] is False
        assert "preserve" in result["error"].lower()

    def test_preserve_allows_same_criterion_in_both(self):
        """Same criterion in improvements AND preserve → accepted."""
        result = evaluate_draft_approach(
            improvements={"E2": [{"plan": "fix the cards", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2"],
            all_criteria_ids=["E1", "E2"],
            preserve={
                "E1": {"what": "hero section impact", "source": "agent_a.2"},
                "E2": {"what": "section header layout", "source": "agent_a.2"},
            },
        )
        assert result["valid"] is True

    def test_preserve_key_must_be_valid_criterion_id(self):
        """Preserve key not in all_criteria_ids → error."""
        result = evaluate_draft_approach(
            improvements={"E1": [{"plan": "fix it", "sources": [], "impact": "structural"}]},
            failed_criteria=["E1"],
            items=["Check 1", "Check 2"],
            all_criteria_ids=["E1", "E2"],
            preserve={"E99": {"what": "something", "source": "agent_a.1"}},
        )
        assert result["valid"] is False
        assert "E99" in result["error"]

    def test_preserve_value_structured(self):
        """Preserve value {"what": "...", "source": "..."} accepted."""
        result = evaluate_draft_approach(
            improvements={"E2": [{"plan": "fix it", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2"],
            all_criteria_ids=["E1", "E2"],
            preserve={"E1": {"what": "hero section impact", "source": "agent_a.2"}},
        )
        assert result["valid"] is True
        assert result["preserve"]["E1"]["what"] == "hero section impact"
        assert result["preserve"]["E1"]["source"] == "agent_a.2"

    def test_preserve_string_value_backward_compat(self):
        """Plain string preserve value auto-wrapped to {"what": str, "source": ""}."""
        result = evaluate_draft_approach(
            improvements={"E2": [{"plan": "fix it", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2"],
            all_criteria_ids=["E1", "E2"],
            preserve={"E1": "hero section impact"},
        )
        assert result["valid"] is True
        assert result["preserve"]["E1"]["what"] == "hero section impact"
        assert result["preserve"]["E1"]["source"] == ""

    def test_preserve_empty_what_rejected(self):
        """Preserve with empty 'what' → error."""
        result = evaluate_draft_approach(
            improvements={"E2": [{"plan": "fix it", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2"],
            all_criteria_ids=["E1", "E2"],
            preserve={"E1": {"what": "", "source": "agent_a.2"}},
        )
        assert result["valid"] is False
        assert "empty" in result["error"].lower()

    def test_task_plan_includes_preserve_entries(self):
        """Task plan has one verify_preserve row AFTER improve entries."""
        result = evaluate_draft_approach(
            improvements={"E2": [{"plan": "fix cards", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2", "Check 3"],
            all_criteria_ids=["E1", "E2", "E3"],
            preserve={
                "E1": {"what": "hero impact", "source": "agent1.2"},
                "E3": {"what": "color palette", "source": "agent1.2"},
            },
        )
        assert result["valid"] is True
        types = [t["type"] for t in result["task_plan"]]
        # Single verify_preserve row at the end, after all improve entries
        verify_indices = [i for i, t in enumerate(types) if t == "verify_preserve"]
        improve_indices = [i for i, t in enumerate(types) if t == "improve"]
        assert len(verify_indices) == 1, "Exactly one verify_preserve row expected"
        assert len(improve_indices) >= 1
        assert min(improve_indices) < verify_indices[0], "verify_preserve must come after improve rows"

    def test_verify_preserve_is_inline_even_when_subagents_enabled(self):
        """Preserve verification is always inline, even when subagents are enabled."""
        state = {**self._NO_GATE, "subagents_enabled": True}
        result = evaluate_draft_approach(
            improvements={"E2": [{"plan": "tighten hierarchy", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2"],
            all_criteria_ids=["E1", "E2"],
            preserve={"E1": {"what": "Hero impact and narrative clarity", "source": "agent1.2"}},
            state=state,
        )
        assert result["valid"] is True
        verify_entry = next(t for t in result["task_plan"] if t["type"] == "verify_preserve")
        assert verify_entry["execution"] == {"mode": "inline"}
        assert "correctness fixes still hold after later changes" in verify_entry["description"]

    def test_result_message_prioritizes_correctness_before_polish(self):
        """Improvement validation message should make blocker correctness precedence explicit."""
        result = evaluate_draft_approach(
            improvements={"E2": [{"plan": "fix cards", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2"],
            all_criteria_ids=["E1", "E2"],
            preserve={"E1": {"what": "hero impact", "source": "agent1.2"}},
        )
        assert result["valid"] is True
        lower = result["message"].lower()
        assert "correctness-critical tasks first" in lower
        assert "verify_preserve" in result["message"]
        assert "correctness fixes still hold" in lower

    def test_task_plan_improve_entries_have_sources(self):
        """Improve entries include plan and sources fields."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "rethink cards", "sources": ["agent2.1"], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=["Check 1", "Check 2"],
            all_criteria_ids=["E1", "E2"],
            preserve={"E2": {"what": "layout", "source": "agent1.2"}},
        )
        assert result["valid"] is True
        improve = [t for t in result["task_plan"] if t["type"] == "improve"][0]
        assert improve["plan"] == "rethink cards"
        assert improve["sources"] == ["agent2.1"]

    def test_preserve_echoed_in_response(self):
        """Response includes preserve dict."""
        result = evaluate_draft_approach(
            improvements={"E2": [{"plan": "fix it", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2"],
            all_criteria_ids=["E1", "E2"],
            preserve={"E1": {"what": "hero impact", "source": "agent1.2"}},
        )
        assert result["valid"] is True
        assert "preserve" in result
        assert "E1" in result["preserve"]

    def test_backward_compat_no_all_criteria_ids(self):
        """Without all_criteria_ids arg, preserve enforcement skipped."""
        result = evaluate_draft_approach(
            improvements={"E2": ["fix fonts"], "E5": ["add timeline"]},
            failed_criteria=["E2", "E5"],
            items=["Check 1", "Check 2", "Check 3", "Check 4", "Check 5"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True

    # --- verify_preserve consolidation ---

    def test_verify_preserve_single_row(self):
        """Multiple preserve entries → exactly one verify_preserve row."""
        result = evaluate_draft_approach(
            improvements={"E2": [{"plan": "fix cards", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2", "Check 3"],
            all_criteria_ids=["E1", "E2", "E3"],
            preserve={
                "E1": {"what": "hero impact", "source": "agent1.2"},
                "E3": {"what": "color palette", "source": "agent1.2"},
            },
        )
        assert result["valid"] is True
        verify_rows = [t for t in result["task_plan"] if t["type"] == "verify_preserve"]
        assert len(verify_rows) == 1

    def test_verify_preserve_after_improve_rows(self):
        """verify_preserve row comes after all improve rows."""
        result = evaluate_draft_approach(
            improvements={
                "E2": [{"plan": "fix cards", "sources": [], "impact": "structural"}],
                "E4": [{"plan": "add animation", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E2", "E4"],
            items=["Check 1", "Check 2", "Check 3", "Check 4"],
            all_criteria_ids=["E1", "E2", "E3", "E4"],
            preserve={"E1": {"what": "hero impact", "source": "agent1.2"}},
        )
        assert result["valid"] is True
        types = [t["type"] for t in result["task_plan"]]
        verify_idx = next(i for i, t in enumerate(types) if t == "verify_preserve")
        improve_indices = [i for i, t in enumerate(types) if t == "improve"]
        assert all(improve_idx < verify_idx for improve_idx in improve_indices)

    def test_verify_preserve_contains_all_items(self):
        """verify_preserve row lists all preserved criteria in its items list."""
        result = evaluate_draft_approach(
            improvements={"E2": [{"plan": "fix cards", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2", "Check 3"],
            all_criteria_ids=["E1", "E2", "E3"],
            preserve={
                "E1": {"what": "hero gradient animation", "source": "agent1.2"},
                "E3": {"what": "sci-fi color palette", "source": "agent2.1"},
            },
        )
        assert result["valid"] is True
        verify_row = next(t for t in result["task_plan"] if t["type"] == "verify_preserve")
        items = verify_row["items"]
        assert len(items) == 2
        criterion_ids = {item["criterion_id"] for item in items}
        assert criterion_ids == {"E1", "E3"}
        e1_item = next(item for item in items if item["criterion_id"] == "E1")
        assert e1_item["what"] == "hero gradient animation"
        assert e1_item["source"] == "agent1.2"

    def test_no_preserve_no_verify_row(self):
        """No preserve entries → no verify_preserve row in task_plan."""
        result = evaluate_draft_approach(
            improvements={"E2": ["fix fonts"], "E5": ["add timeline"]},
            failed_criteria=["E2", "E5"],
            items=["Check 1", "Check 2", "Check 3", "Check 4", "Check 5"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True
        verify_rows = [t for t in result["task_plan"] if t["type"] == "verify_preserve"]
        assert len(verify_rows) == 0


# ---------------------------------------------------------------------------
# Impact gate tests
# ---------------------------------------------------------------------------


class TestImpactGate:
    """Tests for the min_non_incremental impact validation gate."""

    _ITEMS = ["Check 1", "Check 2", "Check 3"]
    _DEFAULT_STATE = {}  # uses default min_structural=1, min_non_incremental=1

    def test_draft_approach_rejects_all_incremental(self):
        """All entries with impact: incremental (default) → fails gate."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "polish layout", "sources": [], "impact": "incremental"}],
                "E2": [{"plan": "tweak colors", "sources": [], "impact": "incremental"}],
            },
            failed_criteria=["E1", "E2"],
            items=self._ITEMS,
            state=self._DEFAULT_STATE,
        )
        assert result["valid"] is False
        assert "impact requirements not met" in result["error"]

    def test_draft_approach_accepts_one_structural(self):
        """One structural improvement → passes (meets min_structural=1)."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "redesign navigation", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=self._DEFAULT_STATE,
        )
        assert result["valid"] is True

    def test_draft_approach_accepts_one_transformative(self):
        """One transformative improvement → passes (meets min_non_incremental=1)."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "switch to 3D engine", "sources": [], "impact": "transformative"}],
            },
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=self._DEFAULT_STATE,
        )
        assert result["valid"] is True

    def test_draft_approach_default_impact_is_incremental(self):
        """Entry with no impact field → treated as incremental, fails gate."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "fix typo", "sources": []}],  # no impact key
            },
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=self._DEFAULT_STATE,
        )
        assert result["valid"] is False
        assert "impact requirements not met" in result["error"]

    def test_draft_approach_min_transformative_gate(self):
        """min_transformative: 1, only structural provided → fails."""
        state = {"improvements": {"min_transformative": 1, "min_structural": 0, "min_non_incremental": 0}}
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "redesign nav", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=state,
        )
        assert result["valid"] is False
        assert "transformative" in result["error"]

    def test_draft_approach_all_gates_disabled(self):
        """All gates set to 0 → all-incremental passes."""
        state = {"improvements": {"min_transformative": 0, "min_structural": 0, "min_non_incremental": 0}}
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "polish layout", "sources": [], "impact": "incremental"}],
            },
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=state,
        )
        assert result["valid"] is True

    def test_draft_approach_combined_floor_fails_with_one(self):
        """min_non_incremental: 2, only one structural → fails."""
        state = {"improvements": {"min_transformative": 0, "min_structural": 0, "min_non_incremental": 2}}
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "redesign", "sources": [], "impact": "structural"}],
                "E2": [{"plan": "polish", "sources": [], "impact": "incremental"}],
            },
            failed_criteria=["E1", "E2"],
            items=self._ITEMS,
            state=state,
        )
        assert result["valid"] is False
        assert "non-incremental combined" in result["error"]

    def test_draft_approach_combined_floor_passes_with_two(self):
        """min_non_incremental: 2, two structural → passes."""
        state = {"improvements": {"min_transformative": 0, "min_structural": 0, "min_non_incremental": 2}}
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "redesign", "sources": [], "impact": "structural"}],
                "E2": [{"plan": "rethink", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E1", "E2"],
            items=self._ITEMS,
            state=state,
        )
        assert result["valid"] is True

    def test_draft_approach_error_suggests_novelty_subagent(self):
        """Error message mentions novelty and quality_rethinking subagents."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "tweak", "sources": [], "impact": "incremental"}],
            },
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=self._DEFAULT_STATE,
        )
        assert result["valid"] is False
        assert "novelty" in result["error"]
        assert "quality_rethinking" in result["error"]

    def test_draft_approach_unknown_impact_coerced_to_incremental(self):
        """Unknown impact value is coerced to incremental, which fails gate."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "do something", "sources": [], "impact": "revolutionary"}],
            },
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=self._DEFAULT_STATE,
        )
        assert result["valid"] is False
        assert "impact requirements not met" in result["error"]

    def test_draft_approach_impact_passed_through_task_plan(self):
        """impact field is included in task_plan improve entries."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "redesign", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=self._DEFAULT_STATE,
        )
        assert result["valid"] is True
        improve_entry = [t for t in result["task_plan"] if t["type"] == "improve"][0]
        assert improve_entry["impact"] == "structural"

    def test_draft_approach_string_entry_treated_as_incremental(self):
        """Plain string improvement → incremental → fails gate."""
        result = evaluate_draft_approach(
            improvements={"E1": ["fix layout"]},
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=self._DEFAULT_STATE,
        )
        assert result["valid"] is False

    def test_draft_approach_no_state_uses_defaults(self):
        """No state passed → default min_structural=1, all-incremental fails."""
        result = evaluate_draft_approach(
            improvements={"E1": [{"plan": "polish", "sources": [], "impact": "incremental"}]},
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=None,
        )
        assert result["valid"] is False


# ---------------------------------------------------------------------------
# Fresh sources + vision field tests
# ---------------------------------------------------------------------------


class TestFreshSourcesAndVision:
    """Tests for 'fresh' sources and optional 'vision' field in draft_approach."""

    _NO_GATE = {"improvements": {"min_transformative": 0, "min_structural": 0, "min_non_incremental": 0}}

    def test_fresh_source_accepted(self):
        """Improvements with sources: ["fresh"] pass validation."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "completely new layout", "sources": ["fresh"], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=["Check 1", "Check 2"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True
        task = [t for t in result["task_plan"] if t["type"] == "improve"][0]
        assert task["sources"] == ["fresh"]

    def test_fresh_and_existing_sources_mixed(self):
        """Improvements can mix 'fresh' with existing answer sources."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "new concept", "sources": ["fresh"], "impact": "structural"}],
                "E2": [{"plan": "keep agent1 nav", "sources": ["agent1.2"], "impact": "incremental"}],
            },
            failed_criteria=["E1", "E2"],
            items=["Check 1", "Check 2"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True

    def test_vision_field_in_task_plan(self):
        """When vision is provided, it appears as a preamble item in task plan."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "redesign hero", "sources": ["fresh"], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=["Check 1"],
            state=self._NO_GATE,
            vision="A stunning single-page site that makes visitors want to learn about gophers",
        )
        assert result["valid"] is True
        # Vision should appear as a guiding preamble in the task plan
        vision_tasks = [t for t in result["task_plan"] if t.get("type") == "vision"]
        assert len(vision_tasks) == 1
        assert "stunning" in vision_tasks[0]["description"]

    def test_vision_field_optional(self):
        """When vision is not provided, task plan has no vision preamble."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "redesign hero", "sources": ["agent1.1"], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=["Check 1"],
            all_criteria_ids=["E1", "E2"],
            preserve={"E2": {"what": "color palette", "source": "agent1.1"}},
            state=self._NO_GATE,
        )
        assert result["valid"] is True
        vision_tasks = [t for t in result["task_plan"] if t.get("type") == "vision"]
        assert len(vision_tasks) == 0

    def test_all_fresh_no_preserve_required(self):
        """When ALL improvements use only fresh sources, preserve is not required."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "brand new approach", "sources": ["fresh"], "impact": "transformative"}],
                "E2": [{"plan": "fresh design system", "sources": ["fresh"], "impact": "structural"}],
            },
            failed_criteria=["E1", "E2"],
            items=["Check 1", "Check 2", "Check 3"],
            all_criteria_ids=["E1", "E2", "E3"],
            preserve={},  # Empty preserve — normally rejected, but all-fresh relaxes this
            state=self._NO_GATE,
        )
        assert result["valid"] is True

    def test_mixed_sources_still_requires_preserve(self):
        """When some improvements use existing sources, preserve is still required."""
        result = evaluate_draft_approach(
            improvements={
                "E1": [{"plan": "new approach", "sources": ["fresh"], "impact": "structural"}],
                "E2": [{"plan": "tweak from agent1", "sources": ["agent1.1"], "impact": "incremental"}],
            },
            failed_criteria=["E1", "E2"],
            items=["Check 1", "Check 2", "Check 3"],
            all_criteria_ids=["E1", "E2", "E3"],
            preserve={},
            state=self._NO_GATE,
        )
        assert result["valid"] is False
        assert "preserve" in result["error"].lower()


# ---------------------------------------------------------------------------
# Simplified submit_checklist (no improvements/substantiveness params)
# ---------------------------------------------------------------------------


class TestSimplifiedSubmitChecklist:
    """Tests that submit_checklist no longer accepts improvements/substantiveness."""

    def test_no_improvements_param(self):
        """evaluate_checklist_submission has no improvements param."""
        import inspect

        sig = inspect.signature(evaluate_checklist_submission)
        assert "improvements" not in sig.parameters

    def test_no_substantiveness_param(self):
        """evaluate_checklist_submission has no substantiveness param."""
        import inspect

        sig = inspect.signature(evaluate_checklist_submission)
        assert "substantiveness" not in sig.parameters

    def test_submit_checklist_returns_failed_criteria(self):
        """Result includes failed_criteria list."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={"E1": 8, "E2": 5},
            report_path="",
            items=items,
            state=state,
        )
        assert result["verdict"] == "new_answer"
        assert "failed_criteria" in result
        assert "E2" in result["failed_criteria"]
        assert "E1" not in result["failed_criteria"]

    def test_submit_checklist_returns_plateaued_criteria(self):
        """Result includes plateaued_criteria when history shows plateau."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        history = [
            {"items_detail": [{"id": "E1", "score": 8}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 8}, {"id": "E2", "score": 5}]},
        ]
        result = evaluate_checklist_submission(
            scores={"E1": 8, "E2": 5},
            report_path="",
            items=items,
            state=state,
            checklist_history=history,
        )
        assert result["verdict"] == "new_answer"
        assert "plateaued_criteria" in result
        # E2 is failing and plateaued — plateaued_criteria is list of dicts
        plateaued_ids = [d["id"] for d in result["plateaued_criteria"]]
        assert "E2" in plateaued_ids

    def test_no_convergence_offramp(self):
        """Result never has convergence_offramp_triggered."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={"E1": 8, "E2": 5},
            report_path="",
            items=items,
            state=state,
        )
        assert "convergence_offramp_triggered" not in result

    def test_draft_approach_instruction_in_iterate_verdict(self):
        """Iterate verdict must instruct agent to call draft_approach."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={"E1": 8, "E2": 5},
            report_path="",
            items=items,
            state=state,
        )
        assert result["verdict"] == "new_answer"
        assert "draft_approach" in result["explanation"]


# ---------------------------------------------------------------------------
# Quality rethinking subagent guidance (per-criterion plateau trigger)
# ---------------------------------------------------------------------------


class TestQualityRethinkingPlateauTrigger:
    """Quality rethinking + novelty subagent guidance fires on per-criterion plateau."""

    def test_plateau_triggers_quality_rethinking_guidance(self):
        """When criteria plateau for 2+ rounds and quality_rethinking enabled, guidance appears."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "quality_rethinking_subagent_enabled": True,
        }
        history = [
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
        ]
        result = evaluate_checklist_submission(
            scores={"E1": 5, "E2": 5},
            report_path="",
            items=items,
            state=state,
            checklist_history=history,
        )
        assert "quality_rethinking" in result["explanation"].lower()

    def test_plateau_triggers_novelty_guidance(self):
        """When criteria plateau and novelty enabled, novelty guidance appears."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "novelty_subagent_enabled": True,
        }
        history = [
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
        ]
        result = evaluate_checklist_submission(
            scores={"E1": 5, "E2": 5},
            report_path="",
            items=items,
            state=state,
            checklist_history=history,
        )
        assert "novelty" in result["explanation"].lower()

    def test_no_plateau_guidance_when_scores_improving(self):
        """No subagent guidance when scores are improving (no plateau)."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 90,
            "quality_rethinking_subagent_enabled": True,
            "novelty_subagent_enabled": True,
        }
        history = [
            {"items_detail": [{"id": "E1", "score": 3}, {"id": "E2", "score": 3}]},
            {"items_detail": [{"id": "E1", "score": 3}, {"id": "E2", "score": 3}]},
        ]
        # Current scores jump significantly — not plateaued
        result = evaluate_checklist_submission(
            scores={"E1": 8, "E2": 8},
            report_path="",
            items=items,
            state=state,
            checklist_history=history,
        )
        assert "quality_rethinking" not in result["explanation"].lower()
        assert "novelty" not in result["explanation"].lower()

    def test_no_plateau_guidance_on_first_answer(self):
        """No plateau guidance on first answer."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": False,
            "required": 2,
            "cutoff": 90,
            "quality_rethinking_subagent_enabled": True,
        }
        result = evaluate_checklist_submission(
            scores={"E1": 5, "E2": 5},
            report_path="",
            items=items,
            state=state,
        )
        assert "quality_rethinking" not in result["explanation"].lower()


class TestPlateauEnrichedDetail:
    """Tests that plateau response includes rich detail for subagent context."""

    def test_plateaued_criteria_result_has_detail_dicts(self):
        """plateaued_criteria in result contains dicts with text and score_history."""
        items = ["First criterion", "Second criterion"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "item_categories": {"E1": "should", "E2": "could"},
        }
        history = [
            {"items_detail": [{"id": "E1", "score": 8}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 8}, {"id": "E2", "score": 5}]},
        ]
        result = evaluate_checklist_submission(
            scores={"E1": 8, "E2": 5},
            report_path="",
            items=items,
            state=state,
            checklist_history=history,
        )
        plateaued = result["plateaued_criteria"]
        assert len(plateaued) >= 1
        e2_detail = next(d for d in plateaued if d["id"] == "E2")
        assert "text" in e2_detail
        assert e2_detail["text"] == "Second criterion"
        assert "score_history" in e2_detail
        assert "category" in e2_detail
        assert e2_detail["category"] == "could"

    def test_plateau_explanation_includes_score_numbers(self):
        """Explanation text includes actual score trajectory numbers."""
        items = ["First criterion", "Second criterion"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "item_categories": {"E1": "should", "E2": "could"},
            "quality_rethinking_subagent_enabled": True,
        }
        history = [
            {"items_detail": [{"id": "E1", "score": 8}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 8}, {"id": "E2", "score": 5}]},
        ]
        result = evaluate_checklist_submission(
            scores={"E1": 8, "E2": 5},
            report_path="",
            items=items,
            state=state,
            checklist_history=history,
        )
        # Explanation should contain score trajectory like "5→5→5"
        explanation = result["explanation"]
        assert "5" in explanation and "→" in explanation

    def test_plateau_guidance_spawns_both_subagents(self):
        """When both quality_rethinking and novelty enabled, guidance says side-by-side."""
        items = ["Criterion A", "Criterion B"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "item_categories": {"E1": "should", "E2": "could"},
            "quality_rethinking_subagent_enabled": True,
            "novelty_subagent_enabled": True,
        }
        history = [
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
        ]
        result = evaluate_checklist_submission(
            scores={"E1": 5, "E2": 5},
            report_path="",
            items=items,
            state=state,
            checklist_history=history,
        )
        explanation = result["explanation"].lower()
        assert "side-by-side" in explanation or "side by side" in explanation
        assert "quality_rethinking" in explanation
        assert "novelty" in explanation


class TestSubagentPatienceCheckpoints:
    """Tests that system prompt includes patience checkpoints."""

    def test_evaluator_checkpoint_in_prompt(self):
        """System prompt has CHECKPOINT before Phase 2 about evaluator results."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        prompt = _build_checklist_gated_decision(
            checklist_items=["Criterion 1", "Criterion 2"],
            evaluator_available=True,
        )
        assert "CHECKPOINT" in prompt
        # Checkpoint must mention evaluator returning before scoring
        idx_checkpoint = prompt.index("CHECKPOINT")
        idx_phase2 = prompt.index("Phase 2")
        assert idx_checkpoint < idx_phase2, "CHECKPOINT must appear before Phase 2"

    def test_builder_checkpoint_in_prompt(self):
        """System prompt has explicit checkpoint about confirming all builders returned."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        prompt = _build_checklist_gated_decision(
            checklist_items=["Criterion 1", "Criterion 2"],
            evaluator_available=True,
        )
        # Must have explicit CHECKPOINT about builder completion
        assert "CHECKPOINT" in prompt
        # Two checkpoints: one for evaluator, one for builders
        checkpoints = [i for i in range(len(prompt)) if prompt[i : i + 10] == "CHECKPOINT"]
        assert len(checkpoints) >= 2, f"Expected 2+ CHECKPOINTs, found {len(checkpoints)}"


class TestBuilderGatedPrompt:
    """Tests that builder-specific prompt sections are gated on builder_enabled."""

    def test_no_builder_guidance_when_disabled(self):
        """When builder_enabled=False, no [builder] annotation or Step 3b in prompt."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        prompt = _build_checklist_gated_decision(
            checklist_items=["Criterion 1", "Criterion 2"],
            builder_enabled=False,
            evaluator_available=True,
        )
        assert "[builder]" not in prompt
        assert "Step 3b" not in prompt
        # Should still have evaluator CHECKPOINT but NOT builder CHECKPOINT
        assert "CHECKPOINT" in prompt
        checkpoints = [i for i in range(len(prompt)) if prompt[i : i + 10] == "CHECKPOINT"]
        assert len(checkpoints) == 1, f"Expected 1 CHECKPOINT (evaluator only), found {len(checkpoints)}"

    def test_builder_guidance_present_by_default(self):
        """By default (builder_enabled=True), builder guidance is present."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        prompt = _build_checklist_gated_decision(
            checklist_items=["Criterion 1", "Criterion 2"],
        )
        assert "[builder]" in prompt
        assert "Step 3b" in prompt

    def test_inline_execution_when_no_builders(self):
        """When builder_enabled=False, Phase 3 says to execute inline."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        prompt = _build_checklist_gated_decision(
            checklist_items=["Criterion 1", "Criterion 2"],
            builder_enabled=False,
        )
        assert "inline" in prompt.lower()


class TestIterationTriggeredQualitySubagents:
    """Tests for iteration-triggered novelty/quality subagent guidance mode."""

    def test_quality_subagent_guidance_fires_without_plateau(self):
        """When both iteration flags are on in round 2+, guidance mentions both subagents."""
        items = ["Criterion A", "Criterion B"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "agent_answer_count": 1,
            "item_categories": {"E1": "should", "E2": "could"},
            "quality_rethinking_subagent_enabled": True,
            "novelty_subagent_enabled": True,
            "enable_quality_rethink_on_iteration": True,
            "enable_novelty_on_iteration": True,
        }
        # No history — so no plateau possible
        result = evaluate_checklist_submission(
            scores={"E1": 5, "E2": 5},
            report_path="",
            items=items,
            state=state,
        )
        explanation = result["explanation"].lower()
        assert "quality_rethinking" in explanation
        assert "novelty" in explanation

    def test_quality_subagent_guidance_includes_failing_criteria_detail(self):
        """Iteration-trigger mode builds detail for all failing criteria, not just plateaued."""
        items = ["First criterion text", "Second criterion text"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "agent_answer_count": 1,
            "item_categories": {"E1": "should", "E2": "could"},
            "quality_rethinking_subagent_enabled": True,
            "novelty_subagent_enabled": False,
            "enable_quality_rethink_on_iteration": True,
            "enable_novelty_on_iteration": False,
        }
        result = evaluate_checklist_submission(
            scores={"E1": 5, "E2": 5},
            report_path="",
            items=items,
            state=state,
        )
        # Should include failing_criteria_detail in result
        assert "failing_criteria_detail" in result
        detail = result["failing_criteria_detail"]
        assert len(detail) == 2
        assert detail[0]["id"] == "E1"
        assert detail[0]["text"] == "First criterion text"
        assert detail[0]["category"] == "should"

    def test_no_guidance_without_flag(self):
        """Without iteration flags, no quality subagent guidance on non-plateaued criteria."""
        items = ["Criterion A", "Criterion B"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "agent_answer_count": 1,
            "quality_rethinking_subagent_enabled": True,
            "novelty_subagent_enabled": True,
            # No iteration-trigger flags
        }
        result = evaluate_checklist_submission(
            scores={"E1": 5, "E2": 5},
            report_path="",
            items=items,
            state=state,
        )
        explanation = result["explanation"].lower()
        # Without plateau, no subagent guidance
        assert "quality_rethinking" not in explanation

    def test_no_guidance_on_round_1_even_with_flags(self):
        """Round 1 should not force iteration-trigger guidance even when flags are set."""
        items = ["Criterion A", "Criterion B"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "agent_answer_count": 0,
            "quality_rethinking_subagent_enabled": True,
            "novelty_subagent_enabled": True,
            "enable_quality_rethink_on_iteration": True,
            "enable_novelty_on_iteration": True,
        }
        result = evaluate_checklist_submission(
            scores={"E1": 5, "E2": 5},
            report_path="",
            items=items,
            state=state,
        )
        explanation = result["explanation"].lower()
        assert "quality_rethinking" not in explanation
        assert "novelty" not in explanation


class TestBuildServerConfig:
    """Tests for build_server_config utility."""

    def test_config_structure(self, tmp_path):
        specs_path = tmp_path / "specs.json"
        config = build_server_config(specs_path)
        assert config["name"] == "massgen_checklist"
        assert config["type"] == "stdio"
        assert config["command"] == "fastmcp"
        assert "--specs" in config["args"]
        assert str(specs_path) in config["args"]


# ---------------------------------------------------------------------------
# Stdio MCP registration (orchestrator wiring)
# ---------------------------------------------------------------------------


class TestChecklistStdioRegistration:
    """Tests for _init_checklist_tool_stdio orchestrator helper.

    Verifies that non-SDK backends with standard MCP infrastructure get the
    checklist stdio MCP server registered automatically.
    """

    def _make_backend(self, *, mcp_servers=None, supports_sdk_mcp=False):
        """Create a minimal mock backend with the attributes the orchestrator checks."""

        class _MockBackend:
            pass

        backend = _MockBackend()
        if mcp_servers is not None:
            backend.mcp_servers = list(mcp_servers)
        backend.supports_sdk_mcp = supports_sdk_mcp
        return backend

    def test_stdio_mcp_added_to_backend_mcp_servers(self, tmp_path, monkeypatch):
        """Backends with mcp_servers=[] get checklist stdio MCP appended."""
        from massgen.orchestrator import Orchestrator

        backend = self._make_backend(mcp_servers=[])
        checklist_state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": False,
            "required": 3,
            "cutoff": 7,
        }
        items = ["Check 1", "Check 2", "Check 3"]
        backend._checklist_state = checklist_state
        backend._checklist_items = items

        # Redirect temp dir to tmp_path for deterministic cleanup
        monkeypatch.setattr("tempfile.mkdtemp", lambda **kw: str(tmp_path / "specs_dir"))
        (tmp_path / "specs_dir").mkdir(exist_ok=True)

        orch = Orchestrator.__new__(Orchestrator)
        orch._init_checklist_tool_stdio("agent_0", backend, checklist_state, items)

        # Stdio MCP config should be appended
        assert len(backend.mcp_servers) == 1
        mcp_entry = backend.mcp_servers[0]
        assert mcp_entry["name"] == "massgen_checklist"
        assert mcp_entry["type"] == "stdio"

        # Specs file should exist with correct content
        specs_path = backend._checklist_specs_path
        assert specs_path.exists()
        data = json.loads(specs_path.read_text())
        assert data["items"] == items
        assert data["state"]["required"] == 3

    def test_specs_file_rewritten_on_refresh(self, tmp_path, monkeypatch):
        """Calling write_checklist_specs with updated state rewrites the file."""
        items = ["Check 1", "Check 2"]
        state_v1 = {"has_existing_answers": False, "required": 2, "cutoff": 70}
        specs_path = tmp_path / "specs.json"
        write_checklist_specs(items, state_v1, specs_path)

        # Simulate orchestrator updating state
        state_v2 = {"has_existing_answers": True, "required": 2, "cutoff": 7, "remaining": 3}
        write_checklist_specs(items, state_v2, specs_path)

        data = json.loads(specs_path.read_text())
        assert data["state"]["has_existing_answers"] is True
        assert data["state"]["remaining"] == 3

    def test_sdk_backend_skipped(self, tmp_path):
        """SDK backends (supports_sdk_mcp=True) should NOT get stdio MCP added."""
        backend = self._make_backend(mcp_servers=[], supports_sdk_mcp=True)
        checklist_state = {"required": 3, "cutoff": 70}
        items = ["Check 1", "Check 2", "Check 3"]
        backend._checklist_state = checklist_state
        backend._checklist_items = items

        # The orchestrator's _init_checklist_tool checks supports_sdk_mcp first,
        # so _init_checklist_tool_stdio is never called for SDK backends.
        # We verify the gate condition directly.
        assert backend.supports_sdk_mcp is True
        # mcp_servers should remain empty — no stdio MCP added
        assert len(backend.mcp_servers) == 0

    def test_codex_backend_skipped(self):
        """Backends without mcp_servers attribute should NOT get stdio MCP added."""
        backend = self._make_backend()  # No mcp_servers attribute
        assert not hasattr(backend, "mcp_servers")

    def test_replaces_existing_checklist_mcp_entry(self, tmp_path, monkeypatch):
        """If a checklist MCP entry already exists, it should be replaced, not duplicated."""
        from massgen.orchestrator import Orchestrator

        existing_mcp = {"name": "massgen_checklist", "type": "stdio", "command": "old"}
        backend = self._make_backend(mcp_servers=[existing_mcp, {"name": "other_tool", "type": "stdio"}])
        checklist_state = {"required": 2, "cutoff": 70}
        items = ["Check 1", "Check 2"]
        backend._checklist_state = checklist_state
        backend._checklist_items = items

        monkeypatch.setattr("tempfile.mkdtemp", lambda **kw: str(tmp_path / "specs_dir"))
        (tmp_path / "specs_dir").mkdir(exist_ok=True)

        orch = Orchestrator.__new__(Orchestrator)
        orch._init_checklist_tool_stdio("agent_0", backend, checklist_state, items)

        # Should have exactly 2 entries: the other_tool + the new checklist
        assert len(backend.mcp_servers) == 2
        names = [s["name"] for s in backend.mcp_servers]
        assert names.count("massgen_checklist") == 1
        assert "other_tool" in names

    def test_checklist_in_framework_mcps(self):
        """massgen_checklist must be in FRAMEWORK_MCPS so it's sent directly to the model.

        Without this, code-based-tools filtering shunts it into a Python
        wrapper that the agent has to discover via filesystem — breaking
        the direct tool-call contract.
        """
        from massgen.filesystem_manager._constants import FRAMEWORK_MCPS
        from massgen.mcp_tools.checklist_tools_server import SERVER_NAME

        assert SERVER_NAME in FRAMEWORK_MCPS, f"{SERVER_NAME!r} missing from FRAMEWORK_MCPS — " f"checklist tool will be filtered out of direct model tools"


class TestChecklistSdkSubmissionCounting:
    """Tests for SDK checklist call quota accounting."""

    @staticmethod
    def _install_fake_claude_agent_sdk(monkeypatch) -> None:
        """Install a minimal claude_agent_sdk stub for orchestrator SDK tool tests."""
        fake_sdk = ModuleType("claude_agent_sdk")

        def tool(**_kwargs):
            def decorator(fn):
                return fn

            return decorator

        def create_sdk_mcp_server(*, name, version, tools):
            return {
                "name": name,
                "version": version,
                "tools": tools,
            }

        fake_sdk.tool = tool
        fake_sdk.create_sdk_mcp_server = create_sdk_mcp_server
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    @pytest.mark.asyncio
    async def test_incomplete_submission_does_not_consume_round_quota(self, monkeypatch):
        """Flat scores (invalid with multiple agents) should not spend the per-round call budget."""
        from massgen.orchestrator import AgentState, Orchestrator

        self._install_fake_claude_agent_sdk(monkeypatch)

        class _MockBackend:
            def __init__(self):
                self.config = {}

        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.config = SimpleNamespace(
            max_checklist_calls_per_round=1,
            checklist_first_answer=False,
        )
        orchestrator.agents = {"agent_0": None, "agent_1": None}
        orchestrator.agent_states = {"agent_0": AgentState(answer_count=1)}

        backend = _MockBackend()
        checklist_state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "require_diagnostic_report": False,
            "available_agent_labels": ["agent1.1", "agent2.1"],
        }
        items = ["Check 1", "Check 2"]

        orchestrator._init_checklist_tool_sdk(
            "agent_0",
            backend,
            checklist_state,
            items,
        )
        submit_checklist = backend.config["mcp_servers"]["massgen_checklist"]["tools"][0]

        invalid_args = {
            "scores": {
                "E1": {"score": 8, "reasoning": "solid"},
                "E2": {"score": 8, "reasoning": "solid"},
            },
        }
        invalid_result = await submit_checklist(invalid_args)
        invalid_payload = json.loads(invalid_result["content"][0]["text"])
        assert invalid_payload["status"] == "validation_error"
        assert invalid_payload["requires_resubmission"] is True
        assert "verdict" not in invalid_payload
        assert invalid_payload.get("incomplete_scores") is True
        assert orchestrator.agent_states["agent_0"].checklist_calls_this_round == 0

        valid_args = {
            "scores": {
                "agent1.1": {
                    "E1": {"score": 8, "reasoning": "solid"},
                    "E2": {"score": 9, "reasoning": "solid"},
                },
                "agent2.1": {
                    "E1": {"score": 7, "reasoning": "solid"},
                    "E2": {"score": 8, "reasoning": "solid"},
                },
            },
        }
        valid_result = await submit_checklist(valid_args)
        valid_payload = json.loads(valid_result["content"][0]["text"])
        assert valid_payload["status"] == "accepted"
        assert valid_payload.get("incomplete_scores") is not True
        assert orchestrator.agent_states["agent_0"].checklist_calls_this_round == 1

        blocked_result = await submit_checklist(valid_args)
        assert blocked_result["isError"] is True
        assert "already called 1 time(s)" in blocked_result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_injection_recheck_allows_delta_or_full_without_consuming_invalid_attempts(self, monkeypatch):
        """After accepted checklist + injection, one extra recheck allows delta-only or full payloads."""
        from massgen.orchestrator import AgentState, Orchestrator

        self._install_fake_claude_agent_sdk(monkeypatch)

        class _MockBackend:
            def __init__(self):
                self.config = {}

        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.config = SimpleNamespace(
            max_checklist_calls_per_round=1,
            checklist_first_answer=False,
        )
        orchestrator.agents = {"agent_0": None, "agent_1": None}
        orchestrator.agent_states = {"agent_0": AgentState(answer_count=1)}

        backend = _MockBackend()
        checklist_state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "require_diagnostic_report": False,
            "available_agent_labels": ["agent1.1", "agent2.1"],
        }
        items = ["Check 1", "Check 2"]

        orchestrator._init_checklist_tool_sdk(
            "agent_0",
            backend,
            checklist_state,
            items,
        )
        submit_checklist = backend.config["mcp_servers"]["massgen_checklist"]["tools"][0]

        first_result = await submit_checklist(
            {
                "scores": {
                    "agent1.1": {"E1": {"score": 9, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "good"}},
                    "agent2.1": {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 8, "reasoning": "good"}},
                },
            },
        )
        first_payload = json.loads(first_result["content"][0]["text"])
        assert first_payload["status"] == "accepted"
        assert first_payload["verdict"] == "vote"
        assert orchestrator.agent_states["agent_0"].checklist_calls_this_round == 1

        # Simulate mid-round injection after first accepted checklist.
        checklist_state["available_agent_labels"] = ["agent1.1", "agent2.2"]
        orchestrator.agent_states["agent_0"].pending_checklist_recheck_labels = {"agent2.2"}

        # Invalid recheck payload should not consume the exception budget.
        invalid_recheck = await submit_checklist(
            {
                "scores": {
                    "E1": {"score": 8, "reasoning": "flat format invalid"},
                    "E2": {"score": 8, "reasoning": "flat format invalid"},
                },
            },
        )
        invalid_payload = json.loads(invalid_recheck["content"][0]["text"])
        assert invalid_payload["status"] == "validation_error"
        assert invalid_payload["requires_resubmission"] is True
        assert "verdict" not in invalid_payload
        assert orchestrator.agent_states["agent_0"].checklist_calls_this_round == 1

        # Delta-only recheck accepted.
        delta_recheck = await submit_checklist(
            {
                "scores": {
                    "agent2.2": {"E1": {"score": 8, "reasoning": "updated"}, "E2": {"score": 8, "reasoning": "updated"}},
                },
            },
        )
        delta_payload = json.loads(delta_recheck["content"][0]["text"])
        assert delta_payload["status"] == "accepted"
        assert delta_payload["verdict"] == "vote"
        assert orchestrator.agent_states["agent_0"].checklist_calls_this_round == 2

        # New injection can re-open allowance; full payload should also be accepted.
        checklist_state["available_agent_labels"] = ["agent1.1", "agent2.3"]
        orchestrator.agent_states["agent_0"].pending_checklist_recheck_labels = {"agent2.3"}

        full_recheck = await submit_checklist(
            {
                "scores": {
                    "agent1.1": {"E1": {"score": 9, "reasoning": "stable"}, "E2": {"score": 9, "reasoning": "stable"}},
                    "agent2.3": {"E1": {"score": 7, "reasoning": "new"}, "E2": {"score": 8, "reasoning": "new"}},
                },
            },
        )
        full_payload = json.loads(full_recheck["content"][0]["text"])
        assert full_payload["status"] == "accepted"
        assert full_payload["verdict"] == "vote"
        assert orchestrator.agent_states["agent_0"].checklist_calls_this_round == 3

        # With no pending injection updates, extra call is blocked again.
        blocked_result = await submit_checklist(
            {
                "scores": {
                    "agent1.1": {"E1": {"score": 9, "reasoning": "stable"}, "E2": {"score": 9, "reasoning": "stable"}},
                    "agent2.3": {"E1": {"score": 7, "reasoning": "new"}, "E2": {"score": 8, "reasoning": "new"}},
                },
            },
        )
        assert blocked_result["isError"] is True
        assert "already called 3 time(s)" in blocked_result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_draft_approach_requires_latest_accepted_iterate(self, monkeypatch):
        """draft_approach is blocked unless latest checklist result is accepted+iterate and recheck is not pending."""
        from massgen.orchestrator import AgentState, Orchestrator

        self._install_fake_claude_agent_sdk(monkeypatch)

        class _MockBackend:
            def __init__(self):
                self.config = {}

        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.config = SimpleNamespace(
            max_checklist_calls_per_round=4,
            checklist_first_answer=False,
            coordination_config=SimpleNamespace(enable_subagents=False),
        )
        orchestrator.agents = {"agent_0": None, "agent_1": None}
        orchestrator.agent_states = {"agent_0": AgentState(answer_count=1)}
        orchestrator._planning_injection_dirs = {}
        orchestrator._write_planning_injection = lambda *_args, **_kwargs: None

        backend = _MockBackend()
        checklist_state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "require_diagnostic_report": False,
            "available_agent_labels": ["agent1.1", "agent2.1"],
        }
        items = ["Hero clarity", "CTA clarity"]

        orchestrator._init_checklist_tool_sdk(
            "agent_0",
            backend,
            checklist_state,
            items,
        )
        submit_checklist = backend.config["mcp_servers"]["massgen_checklist"]["tools"][0]
        draft_approach = backend.config["mcp_servers"]["massgen_checklist"]["tools"][1]

        # 1) Validation error: draft_approach must be blocked.
        invalid_submit = await submit_checklist(
            {
                "scores": {
                    "E1": {"score": 8, "reasoning": "flat format"},
                    "E2": {"score": 8, "reasoning": "flat format"},
                },
            },
        )
        invalid_payload = json.loads(invalid_submit["content"][0]["text"])
        assert invalid_payload["status"] == "validation_error"
        blocked_after_invalid = await draft_approach(
            {
                "improvements": {"E1": [{"plan": "rewrite hero", "sources": ["agent1.1"], "impact": "structural"}]},
                "preserve": {"E2": {"what": "cta clarity", "source": "agent1.1"}},
            },
        )
        blocked_invalid_payload = json.loads(blocked_after_invalid["content"][0]["text"])
        assert blocked_invalid_payload["valid"] is False
        assert "submit_checklist" in blocked_invalid_payload["error"].lower()
        assert "resubmit" in blocked_invalid_payload["error"].lower()

        # 2) Accepted terminate: draft_approach must be blocked.
        accepted_terminate = await submit_checklist(
            {
                "scores": {
                    "agent1.1": {"E1": {"score": 9, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "good"}},
                    "agent2.1": {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 8, "reasoning": "good"}},
                },
            },
        )
        accepted_terminate_payload = json.loads(accepted_terminate["content"][0]["text"])
        assert accepted_terminate_payload["status"] == "accepted"
        assert accepted_terminate_payload["verdict"] == "vote"
        blocked_after_terminate = await draft_approach(
            {
                "improvements": {"E1": [{"plan": "rewrite hero", "sources": ["agent1.1"], "impact": "structural"}]},
                "preserve": {"E2": {"what": "cta clarity", "source": "agent1.1"}},
            },
        )
        blocked_terminate_payload = json.loads(blocked_after_terminate["content"][0]["text"])
        assert blocked_terminate_payload["valid"] is False
        assert "iterate" in blocked_terminate_payload["error"].lower()

        # 3) Accepted iterate on current labels.
        checklist_state["available_agent_labels"] = ["agent1.1", "agent2.2"]
        orchestrator.agent_states["agent_0"].pending_checklist_recheck_labels = {"agent2.2"}
        accepted_iterate = await submit_checklist(
            {
                "scores": {
                    "agent1.1": {"E1": {"score": 5, "reasoning": "weak hero"}, "E2": {"score": 8, "reasoning": "strong cta"}},
                    "agent2.2": {"E1": {"score": 5, "reasoning": "weak hero"}, "E2": {"score": 8, "reasoning": "strong cta"}},
                },
            },
        )
        accepted_iterate_payload = json.loads(accepted_iterate["content"][0]["text"])
        assert accepted_iterate_payload["status"] == "accepted"
        assert accepted_iterate_payload["verdict"] == "new_answer"

        # 4) New injection arrives after accepted iterate -> pending recheck blocks draft_approach.
        checklist_state["available_agent_labels"] = ["agent1.1", "agent2.3"]
        orchestrator.agent_states["agent_0"].pending_checklist_recheck_labels = {"agent2.3"}
        blocked_pending_recheck = await draft_approach(
            {
                "improvements": {"E1": [{"plan": "rewrite hero", "sources": ["agent2.3"], "impact": "structural"}]},
                "preserve": {"E2": {"what": "cta clarity", "source": "agent1.1"}},
            },
        )
        blocked_pending_payload = json.loads(blocked_pending_recheck["content"][0]["text"])
        assert blocked_pending_payload["valid"] is False
        assert "submit_checklist" in blocked_pending_payload["error"].lower()
        assert "agent2.3" in blocked_pending_payload["error"]

        # 5) After re-running checklist on newest labels, draft_approach is allowed.
        accepted_recheck = await submit_checklist(
            {
                "scores": {
                    "agent1.1": {"E1": {"score": 5, "reasoning": "weak hero"}, "E2": {"score": 8, "reasoning": "strong cta"}},
                    "agent2.3": {"E1": {"score": 5, "reasoning": "weak hero"}, "E2": {"score": 8, "reasoning": "strong cta"}},
                },
            },
        )
        accepted_recheck_payload = json.loads(accepted_recheck["content"][0]["text"])
        assert accepted_recheck_payload["status"] == "accepted"
        assert accepted_recheck_payload["verdict"] == "new_answer"

        allowed_propose = await draft_approach(
            {
                "improvements": {"E1": [{"plan": "rewrite hero", "sources": ["agent2.3"], "impact": "structural"}]},
                "preserve": {"E2": {"what": "cta clarity", "source": "agent2.3"}},
            },
        )
        allowed_payload = json.loads(allowed_propose["content"][0]["text"])
        assert allowed_payload["valid"] is True

    @pytest.mark.asyncio
    async def test_sdk_blocks_checklist_loop_after_round_evaluator_auto_injection(self, monkeypatch):
        """Auto-injected evaluator task mode should redirect away from submit_checklist/draft_approach."""
        from massgen.orchestrator import AgentState, Orchestrator

        self._install_fake_claude_agent_sdk(monkeypatch)

        class _MockBackend:
            def __init__(self):
                self.config = {}

        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.config = SimpleNamespace(
            max_checklist_calls_per_round=4,
            checklist_first_answer=False,
            coordination_config=SimpleNamespace(enable_subagents=False),
        )
        orchestrator.agents = {"agent_0": None}
        orchestrator.agent_states = {"agent_0": AgentState(answer_count=1)}
        orchestrator._planning_injection_dirs = {}
        orchestrator._write_planning_injection = lambda *_args, **_kwargs: None

        backend = _MockBackend()
        checklist_state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "require_diagnostic_report": False,
            "available_agent_labels": ["agent1.1"],
            "round_evaluator_auto_injected": True,
            "round_evaluator_primary_artifact_path": "/tmp/eval/critique_packet.md",
            "round_evaluator_next_tasks_artifact_path": "/tmp/eval/next_tasks.json",
            "round_evaluator_strategy_mode": "thesis_shift",
            "round_evaluator_success_contract": {
                "outcome_statement": "The next revision should feel reauthored around a new interaction thesis.",
                "quality_bar": "A reviewer can name the new thesis immediately.",
                "fail_if_any": ["The output still feels like the same brochure with cosmetic tweaks."],
                "required_evidence": ["Fresh screenshots of the rebuilt information architecture"],
            },
        }
        items = ["Hero clarity", "CTA clarity"]

        orchestrator._init_checklist_tool_sdk(
            "agent_0",
            backend,
            checklist_state,
            items,
        )
        submit_checklist = backend.config["mcp_servers"]["massgen_checklist"]["tools"][0]
        draft_approach = backend.config["mcp_servers"]["massgen_checklist"]["tools"][1]

        blocked_submit = await submit_checklist(
            {
                "scores": {
                    "agent1.1": {
                        "E1": {"score": 4, "reasoning": "weak hero"},
                        "E2": {"score": 5, "reasoning": "weak CTA"},
                    },
                },
            },
        )
        submit_text = blocked_submit["content"][0]["text"]
        assert blocked_submit["isError"] is True
        assert "get_task_plan" in submit_text
        assert "new_answer" in submit_text
        assert "submit_checklist" in submit_text and "do not call" in submit_text.lower()
        assert "/tmp/eval/critique_packet.md" in submit_text
        assert "thesis_shift" in submit_text
        assert "The next revision should feel reauthored around a new interaction thesis." in submit_text
        assert "The output still feels like the same brochure with cosmetic tweaks." in submit_text

        blocked_propose = await draft_approach(
            {
                "improvements": {
                    "E1": [{"plan": "rewrite hero", "sources": ["agent1.1"], "impact": "structural"}],
                },
                "preserve": {"E2": {"what": "cta clarity", "source": "agent1.1"}},
            },
        )
        blocked_payload = json.loads(blocked_propose["content"][0]["text"])
        assert blocked_payload["valid"] is False
        assert "get_task_plan" in blocked_payload["error"]
        assert "new_answer" in blocked_payload["error"]
        assert "thesis_shift" in blocked_payload["error"]
        assert "The next revision should feel reauthored around a new interaction thesis." in blocked_payload["error"]

    @pytest.mark.asyncio
    async def test_stdio_blocks_checklist_loop_after_round_evaluator_auto_injection(self, tmp_path):
        """Stdio checklist path should redirect away from checklist/improvement loops in task mode."""
        items = ["Hero clarity", "CTA clarity"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "require_diagnostic_report": False,
            "available_agent_labels": ["agent1.1"],
            "round_evaluator_auto_injected": True,
            "round_evaluator_primary_artifact_path": "/tmp/eval/critique_packet.md",
            "round_evaluator_next_tasks_artifact_path": "/tmp/eval/next_tasks.json",
            "round_evaluator_strategy_mode": "thesis_shift",
            "round_evaluator_success_contract": {
                "outcome_statement": "The next revision should feel reauthored around a new interaction thesis.",
                "quality_bar": "A reviewer can name the new thesis immediately.",
                "fail_if_any": ["The output still feels like the same brochure with cosmetic tweaks."],
                "required_evidence": ["Fresh screenshots of the rebuilt information architecture"],
            },
        }
        specs_path = _make_specs_file(tmp_path, items, state)
        handlers = _build_handlers(specs_path)
        submit_checklist = handlers["submit_checklist"]
        draft_approach = handlers["draft_approach"]

        blocked_submit = json.loads(
            await submit_checklist(
                scores={
                    "agent1.1": {
                        "E1": {"score": 4, "reasoning": "weak hero"},
                        "E2": {"score": 5, "reasoning": "weak CTA"},
                    },
                },
            ),
        )
        assert "get_task_plan" in blocked_submit["error"]
        assert "new_answer" in blocked_submit["error"]
        assert "submit_checklist" in blocked_submit["error"]
        assert "/tmp/eval/critique_packet.md" in blocked_submit["error"]
        assert "thesis_shift" in blocked_submit["error"]
        assert "The next revision should feel reauthored around a new interaction thesis." in blocked_submit["error"]

        blocked_propose = json.loads(
            await draft_approach(
                improvements={
                    "E1": [{"plan": "rewrite hero", "sources": ["agent1.1"], "impact": "structural"}],
                },
                preserve={"E2": {"what": "cta clarity", "source": "agent1.1"}},
            ),
        )
        assert blocked_propose["valid"] is False
        assert "get_task_plan" in blocked_propose["error"]
        assert "new_answer" in blocked_propose["error"]
        assert "Fresh screenshots of the rebuilt information architecture" in blocked_propose["error"]

    @pytest.mark.asyncio
    async def test_stdio_draft_approach_requires_recheck_after_injection(self, tmp_path):
        """Stdio checklist path must block draft_approach when newer injected labels are pending recheck."""
        items = ["Hero clarity", "CTA clarity"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "require_diagnostic_report": False,
            "available_agent_labels": ["agent1.1", "agent2.1"],
        }
        specs_path = _make_specs_file(tmp_path, items, state)
        handlers = _build_handlers(specs_path)
        submit_checklist = handlers["submit_checklist"]
        draft_approach = handlers["draft_approach"]

        accepted_iterate = json.loads(
            await submit_checklist(
                scores={
                    "agent1.1": {"E1": {"score": 5, "reasoning": "weak hero"}, "E2": {"score": 8, "reasoning": "strong cta"}},
                    "agent2.1": {"E1": {"score": 5, "reasoning": "weak hero"}, "E2": {"score": 8, "reasoning": "strong cta"}},
                },
            ),
        )
        assert accepted_iterate["status"] == "accepted"
        assert accepted_iterate["verdict"] == "new_answer"

        state["available_agent_labels"] = ["agent1.1", "agent2.2"]
        state["pending_checklist_recheck_labels"] = ["agent2.2"]
        write_checklist_specs(items, state, specs_path)

        blocked_pending = json.loads(
            await draft_approach(
                improvements={"E1": [{"plan": "rewrite hero", "sources": ["agent2.2"], "impact": "structural"}]},
                preserve={"E2": {"what": "cta clarity", "source": "agent1.1"}},
            ),
        )
        assert blocked_pending["valid"] is False
        assert "submit_checklist" in blocked_pending["error"].lower()
        assert "agent2.2" in blocked_pending["error"]

        accepted_recheck = json.loads(
            await submit_checklist(
                scores={
                    "agent1.1": {"E1": {"score": 5, "reasoning": "weak hero"}, "E2": {"score": 8, "reasoning": "strong cta"}},
                    "agent2.2": {"E1": {"score": 5, "reasoning": "weak hero"}, "E2": {"score": 8, "reasoning": "strong cta"}},
                },
            ),
        )
        assert accepted_recheck["status"] == "accepted"
        assert accepted_recheck["verdict"] == "new_answer"

        specs_after_recheck = _read_specs(specs_path)
        assert specs_after_recheck.get("state", {}).get("pending_checklist_recheck_labels") in ([], None)

        allowed_after_recheck = json.loads(
            await draft_approach(
                improvements={"E1": [{"plan": "rewrite hero", "sources": ["agent2.2"], "impact": "structural"}]},
                preserve={"E2": {"what": "cta clarity", "source": "agent2.2"}},
            ),
        )
        assert allowed_after_recheck["valid"] is True

    @pytest.mark.asyncio
    async def test_stdio_submit_checklist_enforces_first_answer_and_round_quota(self, tmp_path):
        """Stdio checklist path should honor first-answer blocking and persist per-round quota state."""
        items = ["Hero clarity"]
        state = {
            "terminate_action": "stop",
            "iterate_action": "new_answer",
            "has_existing_answers": False,
            "required": 1,
            "cutoff": 7,
            "require_diagnostic_report": False,
            "checklist_first_answer": False,
            "agent_answer_count": 0,
            "max_checklist_calls_per_round": 1,
            "checklist_calls_this_round": 0,
            "checklist_history": [],
            "decomposition_mode": True,
            "current_answer_label": "agent1.1",
        }
        specs_path = _make_specs_file(tmp_path, items, state)
        handlers = _build_handlers(specs_path)
        submit_checklist = handlers["submit_checklist"]

        blocked_first_answer = json.loads(
            await submit_checklist(
                scores={"E1": {"score": 8, "reasoning": "looks solid"}},
            ),
        )
        assert "error" in blocked_first_answer
        assert "before your first answer" in blocked_first_answer["error"].lower()

        state["has_existing_answers"] = True
        state["agent_answer_count"] = 1
        write_checklist_specs(items, state, specs_path)

        accepted = json.loads(
            await submit_checklist(
                scores={"E1": {"score": 8, "reasoning": "subtask is ready"}},
            ),
        )
        assert accepted["status"] == "accepted"
        assert accepted["verdict"] == "stop"

        persisted_after_accept = _read_specs(specs_path)
        persisted_state = persisted_after_accept["state"]
        assert persisted_state["checklist_calls_this_round"] == 1
        assert len(persisted_state["checklist_history"]) == 1

        blocked_repeat = json.loads(
            await submit_checklist(
                scores={"E1": {"score": 8, "reasoning": "still ready"}},
            ),
        )
        assert "error" in blocked_repeat
        assert "already called 1 time(s)" in blocked_repeat["error"]

    @pytest.mark.asyncio
    async def test_sdk_draft_approach_includes_evaluation_input_packet(self, monkeypatch, tmp_path):
        """SDK path should thread checklist evaluation packet into novelty/quality spawn metadata."""
        from massgen.orchestrator import AgentState, Orchestrator

        self._install_fake_claude_agent_sdk(monkeypatch)

        class _MockBackend:
            def __init__(self):
                self.config = {}

        report_path = tmp_path / "diagnostic_report.md"
        report_path.write_text(
            (
                "Failure Patterns\n"
                "- Hero message is vague\n"
                "Root Causes\n"
                "- Missing concrete product behavior\n"
                "Goal Alignment\n"
                "- Path evidence: /tmp/screenshots/hero.png and /tmp/screenshots/cta.png\n"
            ),
            encoding="utf-8",
        )

        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.config = SimpleNamespace(
            max_checklist_calls_per_round=2,
            checklist_first_answer=False,
            coordination_config=SimpleNamespace(enable_subagents=True),
        )
        orchestrator.agents = {"agent_0": None}
        orchestrator.agent_states = {"agent_0": AgentState(answer_count=1)}
        orchestrator._planning_injection_dirs = {}

        backend = _MockBackend()
        checklist_state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "workspace_path": str(tmp_path),
            "subagents_enabled": True,
            "enable_novelty_on_iteration": True,
            "enable_quality_rethink_on_iteration": True,
            "agent_answer_count": 1,
            "item_categories": {"E1": "must", "E2": "should"},
            "quality_rethinking_subagent_enabled": True,
            "novelty_subagent_enabled": True,
        }
        items = ["Hero clarity", "CTA clarity"]

        orchestrator._init_checklist_tool_sdk(
            "agent_0",
            backend,
            checklist_state,
            items,
        )
        submit_checklist = backend.config["mcp_servers"]["massgen_checklist"]["tools"][0]
        draft_approach = backend.config["mcp_servers"]["massgen_checklist"]["tools"][1]

        checklist_result = await submit_checklist(
            {
                "scores": {
                    "E1": {"score": 5, "reasoning": "hero vague"},
                    "E2": {"score": 8, "reasoning": "cta clear"},
                },
                "report_path": str(report_path),
            },
        )
        checklist_payload = json.loads(checklist_result["content"][0]["text"])
        assert checklist_payload["verdict"] == "new_answer"

        propose_result = await draft_approach(
            {
                "improvements": {
                    "E1": [
                        {"plan": "rewrite hero around one concrete product flow", "sources": [], "impact": "structural"},
                    ],
                },
                "preserve": {
                    "E2": {"what": "clear CTA and conversion copy", "source": "agent1.1"},
                },
            },
        )
        propose_payload = json.loads(propose_result["content"][0]["text"])
        assert propose_payload["valid"] is True
        spawn_task = propose_payload["task_plan"][0]
        assert spawn_task["type"] == "novelty_quality_spawn"
        metadata = spawn_task["metadata"]
        assert "evaluation_input" in metadata
        assert metadata["evaluation_input"]["failed_criteria"] == ["E1"]
        assert metadata["evaluation_input"]["diagnostic_report_path"] == str(report_path)
        assert metadata["evaluation_input"]["diagnostic_report_artifact_paths"] == [
            "/tmp/screenshots/hero.png",
            "/tmp/screenshots/cta.png",
        ]
        assert "subagent_task_templates" in metadata


@pytest.mark.asyncio
async def test_checklist_create_server_standalone_with_hook_dir(
    monkeypatch,
    tmp_path,
):
    """Standalone file-path loading must support --hook-dir without import errors."""
    import importlib.util

    server_path = Path(__file__).parent.parent / "mcp_tools" / "checklist_tools_server.py"
    assert server_path.exists(), f"Expected server file at {server_path}"

    specs_path = tmp_path / "checklist_specs.json"
    specs_path.write_text(
        json.dumps(
            {
                "items": ["T1"],
                "state": {
                    "required": 1,
                    "cutoff": 7,
                    "has_existing_answers": True,
                },
            },
        ),
        encoding="utf-8",
    )
    hook_dir = tmp_path / "hook_ipc"
    hook_dir.mkdir(parents=True, exist_ok=True)

    spec = importlib.util.spec_from_file_location("checklist_tools_server", server_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["checklist_tools_server"] = module
    try:
        spec.loader.exec_module(module)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "checklist_tools_server.py",
                "--specs",
                str(specs_path),
                "--hook-dir",
                str(hook_dir),
            ],
        )
        server = await module.create_server()
    finally:
        sys.modules.pop("checklist_tools_server", None)

    available_tools = {tool.name for tool in server._tool_manager._tools.values()}
    assert "submit_checklist" in available_tools


# ---------------------------------------------------------------------------
# Diagnostic Report Gate
# ---------------------------------------------------------------------------


class TestDiagnosticReportGate:
    """Tests for required diagnostic report in checklist_gated mode."""

    def _make_state(self, tmp_path, require_report=True, has_existing=True):
        """Build a minimal state dict with diagnostic report gate enabled."""
        return {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": has_existing,
            "required": 2,
            "cutoff": 7,
            "require_diagnostic_report": require_report,
            "workspace_path": str(tmp_path),
        }

    def _passing_scores(self):
        return {"E1": 80, "E2": 85}

    def test_missing_report_rejected_when_required(self, tmp_path):
        """No report_path + gate active -> verdict overridden, gate triggered."""
        state = self._make_state(tmp_path)
        result = evaluate_checklist_submission(
            scores=self._passing_scores(),
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["status"] == "validation_error"
        assert result["requires_resubmission"] is True
        assert result["report_gate_triggered"] is True
        assert "verdict" not in result

    def test_empty_report_rejected(self, tmp_path):
        """Empty report file -> rejected."""
        report = tmp_path / "diagnostic_report.md"
        report.write_text("")
        state = self._make_state(tmp_path)
        result = evaluate_checklist_submission(
            scores=self._passing_scores(),
            report_path=str(report),
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["status"] == "validation_error"
        assert result["requires_resubmission"] is True
        assert result["report_gate_triggered"] is True
        assert "verdict" not in result

    def test_too_short_report_rejected(self, tmp_path):
        """Report with < 100 chars -> rejected as lacking substance."""
        report = tmp_path / "diagnostic_report.md"
        report.write_text("Some notes.")
        state = self._make_state(tmp_path)
        result = evaluate_checklist_submission(
            scores=self._passing_scores(),
            report_path=str(report),
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["status"] == "validation_error"
        assert result["requires_resubmission"] is True
        assert result["report_gate_triggered"] is True
        assert "verdict" not in result

    def test_substantial_report_accepted(self, tmp_path):
        """Report with real diagnostic content -> gate passes, scores determine verdict."""
        report = tmp_path / "diagnostic_report.md"
        report.write_text(
            "## Failure Patterns\n\n"
            "The login form has no error states. The CSS layout breaks on mobile.\n\n"
            "## Root Causes\n\n"
            "The responsive design was not tested across viewport sizes.\n\n"
            "## Goal Alignment\n\n"
            "The core request was a responsive website but mobile is broken.\n",
        )
        state = self._make_state(tmp_path)
        result = evaluate_checklist_submission(
            scores=self._passing_scores(),
            report_path=str(report),
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["report_gate_triggered"] is False
        assert result["verdict"] == "vote"  # scores pass, report passes

    def test_report_content_captured(self, tmp_path):
        """Report content should be included in result for logging."""
        report = tmp_path / "diagnostic_report.md"
        content = "## Failure Patterns\n\nLogin form has no error states.\n\n" "## Root Causes\n\nMissing validation logic.\n\n" "## Goal Alignment\n\nCore requirements partially met.\n"
        report.write_text(content)
        state = self._make_state(tmp_path)
        result = evaluate_checklist_submission(
            scores=self._passing_scores(),
            report_path=str(report),
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["report"]["content"] == content

    def test_gate_skipped_on_first_answer(self, tmp_path):
        """First answer (has_existing_answers=False) -> gate not applied."""
        state = self._make_state(tmp_path, has_existing=False)
        result = evaluate_checklist_submission(
            scores=self._passing_scores(),
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
        )
        # First answer always iterates, but NOT because of report gate
        assert result["report_gate_triggered"] is False

    def test_gate_inactive_by_default(self, tmp_path):
        """No require_diagnostic_report in state -> backward compat, no gate."""
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 1,
            "cutoff": 7,
            # No require_diagnostic_report key at all
        }
        result = evaluate_checklist_submission(
            scores={"E1": 9},
            report_path="",
            items=["Check 1"],
            state=state,
        )
        assert result["report_gate_triggered"] is False
        assert result["verdict"] == "vote"

    def test_report_required_in_changedoc_mode_too(self, tmp_path):
        """Changedoc mode still requires separate diagnostic report."""
        state = self._make_state(tmp_path)
        state["changedoc_mode"] = True  # changedoc active
        result = evaluate_checklist_submission(
            scores=self._passing_scores(),
            report_path="",  # no separate report
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["report_gate_triggered"] is True

    def test_external_round_evaluator_packet_path_allowed_when_whitelisted(self, tmp_path):
        """Fallback checklist mode should accept the exact evaluator packet path directly."""
        parent_workspace = tmp_path / "parent"
        parent_workspace.mkdir()
        evaluator_workspace = tmp_path / "evaluator"
        evaluator_workspace.mkdir()
        report = evaluator_workspace / "critique_packet.md"
        report.write_text(
            "## Failure Patterns\n\nThe hero is generic and the mobile layout breaks.\n\n"
            "## Root Causes\n\nThe current structure is brochure-first instead of route-first.\n\n"
            "## Goal Alignment\n\nThe work still misses the experience bar on clarity and distinctiveness.\n",
            encoding="utf-8",
        )
        state = self._make_state(parent_workspace)
        state["allowed_external_report_paths"] = [str(report)]

        resolved, error = _resolve_report_file(str(report), state)

        assert error is None
        assert resolved == report.resolve()

        result = evaluate_checklist_submission(
            scores=self._passing_scores(),
            report_path=str(report),
            items=["Check 1", "Check 2"],
            state=state,
        )

        assert result["report_gate_triggered"] is False
        assert result["report"]["resolved_path"] == str(report.resolve())

    def test_external_report_path_still_rejected_without_whitelist(self, tmp_path):
        """Arbitrary paths outside the workspace should remain blocked."""
        parent_workspace = tmp_path / "parent"
        parent_workspace.mkdir()
        external_report = tmp_path / "elsewhere" / "diagnostic_report.md"
        external_report.parent.mkdir()
        external_report.write_text("diagnostic content that should not be allowed", encoding="utf-8")
        state = self._make_state(parent_workspace)

        resolved, error = _resolve_report_file(str(external_report), state)

        assert resolved is None
        assert "workspace" in (error or "").lower()


# ---------------------------------------------------------------------------
# Per-agent scores format
# ---------------------------------------------------------------------------


class TestPerAgentScores:
    """Tests for the per-agent scores format where each agent is scored separately."""

    def _base_state(self):
        return {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "require_gap_report": False,
        }

    def test_best_agent_passes_returns_terminate(self):
        """Best agent's scores clear the bar → vote."""
        scores = {
            "agent1": {"E1": {"score": 8, "reasoning": "solid"}, "E2": {"score": 9, "reasoning": "great"}},
            "agent2": {"E1": {"score": 5, "reasoning": "weak"}, "E2": {"score": 6, "reasoning": "ok"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=self._base_state(),
        )
        assert result["verdict"] == "vote"
        assert result["best_agent"] == "agent1"
        assert result["true_count"] == 2

    def test_best_agent_fails_returns_iterate(self):
        """Even the best agent fails a dimension → new_answer."""
        scores = {
            "agent1": {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 4, "reasoning": "poor"}},
            "agent2": {"E1": {"score": 6, "reasoning": "ok"}, "E2": {"score": 5, "reasoning": "poor"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=self._base_state(),
        )
        assert result["verdict"] == "new_answer"
        assert result["best_agent"] == "agent1"  # agent1 has higher aggregate
        assert result["true_count"] == 1

    def test_best_agent_selected_by_aggregate(self):
        """Agent with highest total score is selected as best."""
        scores = {
            "agent1": {"E1": {"score": 9, "reasoning": "great"}, "E2": {"score": 5, "reasoning": "weak"}},
            "agent2": {"E1": {"score": 7, "reasoning": "good"}, "E2": {"score": 8, "reasoning": "solid"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=self._base_state(),
        )
        # agent1 total=14, agent2 total=15 → agent2 wins
        assert result["best_agent"] == "agent2"

    def test_per_agent_breakdown_included_in_response(self):
        """Response includes full per-agent score breakdown."""
        scores = {
            "agent1": {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "great"}},
            "agent2": {"E1": {"score": 5, "reasoning": "weak"}, "E2": {"score": 6, "reasoning": "ok"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=self._base_state(),
        )
        assert "per_agent_scores" in result
        assert "agent1" in result["per_agent_scores"]
        assert "agent2" in result["per_agent_scores"]

    def test_flat_scores_still_work_backward_compat(self):
        """Legacy flat E-keyed scores still produce correct verdicts."""
        scores = {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "great"}}
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=self._base_state(),
        )
        assert result["verdict"] == "vote"
        assert result["true_count"] == 2
        # No best_agent key for flat format
        assert "best_agent" not in result

    def test_single_agent_per_agent_format(self):
        """Single agent in per-agent format works correctly."""
        scores = {
            "agent1": {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "great"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=self._base_state(),
        )
        assert result["verdict"] == "vote"
        assert result["best_agent"] == "agent1"

    def test_per_agent_incomplete_scores_rejected(self):
        """Per-agent format: best agent missing a criterion triggers rejection."""
        scores = {
            "agent1": {"E1": {"score": 8, "reasoning": "good"}},  # missing E2
            "agent2": {"E1": {"score": 5, "reasoning": "weak"}, "E2": {"score": 6, "reasoning": "ok"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=self._base_state(),
        )
        assert result["status"] == "validation_error"
        assert result["requires_resubmission"] is True
        assert result.get("incomplete_scores") is True
        assert "verdict" not in result


# ---------------------------------------------------------------------------
# Novelty guidance injection (Step 3 of round lifecycle plan)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Per-criterion plateau detection
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Available agent labels enforcement
# ---------------------------------------------------------------------------


class TestAvailableAgentLabelsCoverage:
    """When available_agent_labels is provided in state, all labels must be scored.

    Regression test: agents were submitting per-agent scores that only covered their
    own answer (flat or single-agent format), silently omitting peer agents from
    evaluation.
    """

    def _base_state(self, **extra):
        return {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "require_gap_report": False,
            **extra,
        }

    def test_missing_available_agent_triggers_rejection(self):
        """Scores dict omits an available agent → iterate with clear explanation."""
        state = self._base_state(available_agent_labels=["agent1", "agent2"])
        scores = {
            # Only agent1 scored; agent2 is available but missing
            "agent1": {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "great"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["status"] == "validation_error"
        assert result["requires_resubmission"] is True
        assert result.get("incomplete_scores") is True
        assert "verdict" not in result
        assert "agent2" in result.get("explanation", "").lower()

    def test_all_available_agents_scored_passes(self):
        """Scoring all available agents succeeds normally."""
        state = self._base_state(available_agent_labels=["agent1", "agent2"])
        scores = {
            "agent1": {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "great"}},
            "agent2": {"E1": {"score": 6, "reasoning": "ok"}, "E2": {"score": 7, "reasoning": "decent"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["verdict"] == "vote"
        assert not result.get("incomplete_scores")

    def test_no_available_labels_in_state_no_enforcement(self):
        """Without available_agent_labels in state, single-agent submission is fine."""
        state = self._base_state()  # no available_agent_labels key
        scores = {
            "agent1": {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "great"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["verdict"] == "vote"
        assert not result.get("incomplete_scores")

    def test_three_agents_two_missing_rejected(self):
        """Multiple missing agents all named in error message."""
        state = self._base_state(available_agent_labels=["agent1", "agent2", "agent3"])
        scores = {
            "agent1": {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "great"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["status"] == "validation_error"
        assert result["requires_resubmission"] is True
        assert result.get("incomplete_scores") is True
        assert "verdict" not in result
        explanation = result.get("explanation", "").lower()
        assert "agent2" in explanation
        assert "agent3" in explanation

    def test_flat_format_with_available_labels_rejected(self):
        """Flat (non-per-agent) scores with available_agent_labels present → rejected."""
        state = self._base_state(available_agent_labels=["agent1", "agent2"])
        # Flat format only covers one implicit answer, not all available agents
        scores = {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "great"}}
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["status"] == "validation_error"
        assert result["requires_resubmission"] is True
        assert result.get("incomplete_scores") is True
        assert "verdict" not in result


# ---------------------------------------------------------------------------
# _convert_task_plan_to_inject_format
# ---------------------------------------------------------------------------


class TestConvertTaskPlanToInjectFormat:
    """Tests for _convert_task_plan_to_inject_format helper."""

    def test_convert_improve_item(self):
        """Improve task_plan item converts to correct injection format."""
        from massgen.mcp_tools.checklist_tools_server import (
            _convert_task_plan_to_inject_format,
        )

        task_plan = [
            {
                "type": "improve",
                "criterion_id": "E2",
                "criterion": "Uses vivid imagery",
                "plan": "Add more sensory details in stanza 2",
                "sources": ["agent1.1"],
            },
        ]

        result = _convert_task_plan_to_inject_format(task_plan)

        assert len(result) == 1
        task = result[0]
        assert task["description"] == "[E2] Add more sensory details in stanza 2"
        assert task["verification"] == "Uses vivid imagery"
        assert task["priority"] == "high"
        assert task["metadata"]["criterion_id"] == "E2"
        assert task["metadata"]["type"] == "improve"
        assert task["metadata"]["sources"] == ["agent1.1"]
        assert task["metadata"]["injected"] is True

    def test_convert_verify_preserve_item(self):
        """verify_preserve task_plan item converts to a single consolidated injection task."""
        from massgen.mcp_tools.checklist_tools_server import (
            _convert_task_plan_to_inject_format,
        )

        task_plan = [
            {
                "type": "verify_preserve",
                "description": "Before submitting: verify these strengths haven't regressed",
                "items": [
                    {"criterion_id": "E1", "what": "Warm conversational tone in intro", "source": "agent2.1"},
                    {"criterion_id": "E3", "what": "Color palette coherence", "source": "agent1.2"},
                ],
                "priority": "high",
            },
        ]

        result = _convert_task_plan_to_inject_format(task_plan)

        assert len(result) == 1
        task = result[0]
        assert "Before submitting" in task["description"]
        assert "[E1]" in task["description"]
        assert "Warm conversational tone" in task["description"]
        assert "[E3]" in task["description"]
        assert task["priority"] == "high"
        assert task["verification"] == (
            "All preserved elements verified in actual output (run/render/screenshot as appropriate), "
            "not just present in source files; preserved strengths intact; earlier correctness fixes still pass after later changes; passing criteria scores confirmed not dropped"
        )
        assert task["metadata"]["type"] == "verify_preserve"
        assert len(task["metadata"]["items"]) == 2
        assert task["metadata"]["injected"] is True
        assert "correctness fixes still pass after later changes" in task["description"]

    def test_convert_verify_preserve_item_preserves_execution(self):
        """verify_preserve conversion should preserve evaluator/critic delegation execution."""
        from massgen.mcp_tools.checklist_tools_server import (
            _convert_task_plan_to_inject_format,
        )

        task_plan = [
            {
                "type": "verify_preserve",
                "description": "Before submitting: verify these strengths haven't regressed",
                "items": [
                    {"criterion_id": "E1", "what": "Warm conversational tone in intro", "source": "agent2.1"},
                ],
                "priority": "high",
                "execution": {"mode": "delegate", "subagent_type": "evaluator"},
            },
        ]

        result = _convert_task_plan_to_inject_format(task_plan)
        assert len(result) == 1
        assert result[0]["execution"] == {"mode": "delegate", "subagent_type": "evaluator"}
        assert result[0]["metadata"]["execution"] == {"mode": "delegate", "subagent_type": "evaluator"}

    def test_convert_verify_preserve_item_includes_blind_comparison_instruction(self):
        """verify_preserve conversion should include anti-bias blind comparison guidance."""
        from massgen.mcp_tools.checklist_tools_server import (
            _convert_task_plan_to_inject_format,
        )

        task_plan = [
            {
                "type": "verify_preserve",
                "description": "Before submitting: verify these strengths haven't regressed",
                "items": [
                    {"criterion_id": "E1", "what": "Warm conversational tone in intro", "source": "agent2.1"},
                ],
                "priority": "high",
                "execution": {"mode": "delegate", "subagent_type": "evaluator"},
            },
        ]

        result = _convert_task_plan_to_inject_format(task_plan)
        assert len(result) == 1
        assert "without revealing which answer is yours" in result[0]["description"]

    def test_convert_mixed_items(self):
        """Improve and verify_preserve items in a single task_plan convert correctly."""
        from massgen.mcp_tools.checklist_tools_server import (
            _convert_task_plan_to_inject_format,
        )

        task_plan = [
            {
                "type": "improve",
                "criterion_id": "E3",
                "criterion": "Includes examples",
                "plan": "Add 3 concrete examples",
                "sources": [],
            },
            {
                "type": "verify_preserve",
                "description": "Before submitting: verify these strengths haven't regressed",
                "items": [
                    {"criterion_id": "E1", "what": "Hook in first line", "source": "agent1.1"},
                ],
                "priority": "high",
            },
        ]

        result = _convert_task_plan_to_inject_format(task_plan)

        assert len(result) == 2
        assert result[0]["metadata"]["type"] == "improve"
        assert result[1]["metadata"]["type"] == "verify_preserve"

    def test_convert_novelty_quality_spawn_preserves_evaluation_metadata(self):
        """Spawn conversion should preserve evaluation packet and template metadata."""
        from massgen.mcp_tools.checklist_tools_server import (
            _convert_task_plan_to_inject_format,
        )

        task_plan = [
            {
                "id": "novelty_quality_spawn",
                "type": "novelty_quality_spawn",
                "description": "Spawn novelty/quality in background",
                "priority": "high",
                "metadata": {
                    "type": "novelty_quality_spawn",
                    "failing_criteria": ["E1"],
                    "spawn_novelty": True,
                    "spawn_quality_rethinking": True,
                    "evaluation_input": {
                        "failed_criteria": ["E1"],
                        "failing_criteria_detail": [
                            {"id": "E1", "text": "Hero clarity", "category": "must", "current_score": 5},
                        ],
                        "diagnostic_report_path": "/tmp/report.md",
                        "diagnostic_report_artifact_paths": ["/tmp/screenshots/hero.png"],
                    },
                    "subagent_task_templates": {
                        "novelty_task_template": "Evaluation Input (verbatim): ...",
                        "quality_rethinking_task_template": "Evaluation Input (verbatim): ...",
                    },
                },
            },
        ]

        result = _convert_task_plan_to_inject_format(task_plan)
        assert len(result) == 1
        metadata = result[0]["metadata"]
        assert metadata["evaluation_input"]["failed_criteria"] == ["E1"]
        assert metadata["evaluation_input"]["diagnostic_report_path"] == "/tmp/report.md"
        assert metadata["subagent_task_templates"]["novelty_task_template"].startswith(
            "Evaluation Input (verbatim):",
        )


# ---------------------------------------------------------------------------
# _write_inject_file
# ---------------------------------------------------------------------------


class TestWriteInjectFile:
    """Tests for _write_inject_file helper that writes injection files."""

    def test_draft_approach_writes_inject_file(self, tmp_path):
        """Valid draft_approach result + injection_dir → file written with correct format."""
        from massgen.mcp_tools.checklist_tools_server import _write_inject_file

        task_plan = [
            {
                "type": "improve",
                "criterion_id": "E1",
                "criterion": "Clear structure",
                "plan": "Add section headers",
                "sources": ["agent1.1"],
            },
        ]

        _write_inject_file(tmp_path, task_plan)

        inject_file = tmp_path / "inject_tasks.json"
        assert inject_file.exists()

        data = json.loads(inject_file.read_text())
        assert len(data) == 1
        assert data[0]["description"] == "[E1] Add section headers"
        assert data[0]["metadata"]["injected"] is True

    def test_draft_approach_creates_missing_dir(self, tmp_path):
        """_write_inject_file creates the injection directory if it doesn't exist."""
        from massgen.mcp_tools.checklist_tools_server import _write_inject_file

        missing_dir = tmp_path / "nonexistent" / "nested"
        assert not missing_dir.exists()

        task_plan = [
            {
                "type": "improve",
                "criterion_id": "E1",
                "criterion": "Clear structure",
                "plan": "Add section headers",
                "sources": ["agent1.1"],
            },
        ]

        _write_inject_file(missing_dir, task_plan)

        inject_file = missing_dir / "inject_tasks.json"
        assert inject_file.exists()
        data = json.loads(inject_file.read_text())
        assert len(data) == 1

    def test_draft_approach_no_inject_when_no_dir(self):
        """No injection_dir → no file written, no error."""
        from massgen.mcp_tools.checklist_tools_server import _write_inject_file

        # Should be a safe no-op
        _write_inject_file(None, [{"type": "improve", "criterion_id": "E1", "criterion": "x", "plan": "y", "sources": []}])

    def test_verify_preserve_written_to_inject_file(self, tmp_path):
        """verify_preserve task_plan row → correct entry in inject_tasks.json."""
        from massgen.mcp_tools.checklist_tools_server import _write_inject_file

        task_plan = [
            {
                "type": "improve",
                "criterion_id": "E2",
                "criterion": "Clear structure",
                "plan": "Add section headers",
                "sources": ["agent1.1"],
            },
            {
                "type": "verify_preserve",
                "description": "Before submitting: verify these strengths haven't regressed",
                "items": [
                    {"criterion_id": "E1", "what": "Hero animation", "source": "agent2.1"},
                ],
                "priority": "high",
            },
        ]

        _write_inject_file(tmp_path, task_plan)

        inject_file = tmp_path / "inject_tasks.json"
        data = json.loads(inject_file.read_text())
        assert len(data) == 2
        verify_entry = next(d for d in data if d["metadata"]["type"] == "verify_preserve")
        assert "Before submitting" in verify_entry["description"]
        assert "[E1]" in verify_entry["description"]
        assert verify_entry["priority"] == "high"
