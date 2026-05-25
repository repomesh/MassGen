"""Canonical score-extraction helpers (consolidation refactor).

`extract_score` and `is_per_agent_scores` replace three divergent copies that
existed in checklist_tools_server.py (`_extract_score`, `_is_per_agent_scores`),
quality_server.py (`_extract_score`), and bootstrap_criteria.py (`_coerce_score`).
This locks the single canonical behavior the call sites now delegate to.
"""

from massgen.score_utils import extract_score, is_per_agent_scores


class TestExtractScore:
    def test_plain_int_and_float(self):
        assert extract_score(9) == 9
        assert extract_score(8.5) == 8.5

    def test_score_dict(self):
        assert extract_score({"score": 7, "reasoning": "x"}) == 7

    def test_missing_or_non_numeric_returns_default(self):
        assert extract_score({"reasoning": "no score"}) == 0  # default 0
        assert extract_score("nope") == 0
        assert extract_score(None) == 0

    def test_custom_default_for_filtering(self):
        # bootstrap_criteria needs None to skip non-numeric entries.
        assert extract_score({"reasoning": "x"}, default=None) is None
        assert extract_score(None, default=None) is None
        assert extract_score({"score": 4}, default=None) == 4

    def test_bool_is_rejected(self):
        # bool is an int subclass; a True/False must not count as a numeric score.
        assert extract_score(True) == 0
        assert extract_score({"score": False}, default=None) is None


class TestIsPerAgentScores:
    def test_flat_shape_is_not_per_agent(self):
        assert is_per_agent_scores({"E1": {"score": 9}, "E2": {"score": 4}}) is False

    def test_per_agent_shape_detected(self):
        scores = {"agent1.1": {"E1": {"score": 9}}, "agent2.1": {"E1": {"score": 4}}}
        assert is_per_agent_scores(scores) is True

    def test_empty_is_not_per_agent(self):
        assert is_per_agent_scores({}) is False

    def test_respects_item_prefix(self):
        # With a non-default prefix, E-keys would look "per-agent" unless T/E guard catches them.
        assert is_per_agent_scores({"E1": {"score": 9}}, item_prefix="C") is False  # E guard
        assert is_per_agent_scores({"agentX": {}}, item_prefix="C") is True
