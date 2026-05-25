"""Per-criterion textual feedback threaded across rounds (Pillar 5, Reflexion).

The checklist already collects per-criterion ``reasoning`` in submitted scores,
but that text was discarded after the verdict (``failing_criteria_detail`` keeps
only id/text/category/score). Scores compress away the gradient; the reasoning
text IS the gradient. These helpers extract that reasoning and format it into a
memo that is queued for the next round's generator via the orchestrator's
``_queue_round_start_context_block`` seam.

Pure helpers under test live in ``massgen/mcp_tools/checklist_tools_server.py``:
  - ``extract_criterion_feedback`` — {criterion_id: reasoning} from flat or
    per-agent score shapes (per-agent keeps the lowest-scoring agent's reasoning,
    the most diagnostic signal for what to fix).
  - ``format_criterion_feedback_memo`` — render the memo, marking failed criteria.
"""

from unittest.mock import patch

from massgen.mcp_tools.checklist_tools_server import (
    extract_criterion_feedback,
    format_criterion_feedback_memo,
)
from massgen.orchestrator import Orchestrator


class TestExtractCriterionFeedback:
    def test_flat_scores(self):
        scores = {
            "E1": {"score": 9, "reasoning": "solid intro"},
            "E2": {"score": 4, "reasoning": "missing examples"},
        }
        fb = extract_criterion_feedback(scores)
        assert fb == {"E1": "solid intro", "E2": "missing examples"}

    def test_per_agent_keeps_lowest_score_reasoning(self):
        scores = {
            "agent1.1": {"E1": {"score": 8, "reasoning": "ok depth"}},
            "agent2.1": {"E1": {"score": 3, "reasoning": "shallow, no sources"}},
        }
        fb = extract_criterion_feedback(scores)
        # Lowest score (3) is the most diagnostic -> its reasoning wins.
        assert fb["E1"] == "shallow, no sources"

    def test_entries_without_reasoning_skipped(self):
        scores = {
            "E1": {"score": 9},  # no reasoning
            "E2": {"score": 4, "reasoning": "weak conclusion"},
        }
        assert extract_criterion_feedback(scores) == {"E2": "weak conclusion"}

    def test_non_dict_returns_empty(self):
        assert extract_criterion_feedback("nope") == {}
        assert extract_criterion_feedback({}) == {}


class TestFormatCriterionFeedbackMemo:
    def test_empty_feedback_is_empty_string(self):
        assert format_criterion_feedback_memo({}) == ""

    def test_memo_lists_each_criterion(self):
        memo = format_criterion_feedback_memo(
            {"E2": "missing examples", "E1": "solid intro"},
        )
        assert "E1" in memo and "E2" in memo
        assert "solid intro" in memo
        assert "missing examples" in memo
        # E1 should be listed before E2 (numeric ordering, not dict order).
        assert memo.index("E1") < memo.index("E2")

    def test_failed_criteria_are_marked(self):
        memo = format_criterion_feedback_memo(
            {"E1": "ok", "E2": "missing examples"},
            failed_ids=["E2"],
        )
        # The failed criterion line should carry a visible marker the passing one lacks.
        e2_line = next(line for line in memo.splitlines() if line.lstrip("- ").startswith("E2"))
        e1_line = next(line for line in memo.splitlines() if line.lstrip("- ").startswith("E1"))
        assert "FAILED" in e2_line
        assert "FAILED" not in e1_line


class TestFeedbackMemoRoundTrip:
    """The memo must reach the next round via the round-start context seam."""

    def test_queued_memo_surfaces_then_clears(self):
        with patch.object(Orchestrator, "__init__", lambda self, **kw: None):
            orch = Orchestrator()
        orch._round_start_context_blocks = {}
        memo = format_criterion_feedback_memo(
            {"E2": "missing examples"},
            failed_ids=["E2"],
        )
        orch._queue_round_start_context_block("agent_a", memo)

        surfaced = orch._consume_round_start_context_block("agent_a")
        assert surfaced is not None
        assert "CRITERION FEEDBACK" in surfaced
        assert "missing examples" in surfaced
        # Consumed once -> not repeated on the round after.
        assert orch._consume_round_start_context_block("agent_a") is None
