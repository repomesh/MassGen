"""Discriminative-power pruning of free-pass criteria (Pillar 4).

Bootstrap criteria emergence only *adds* criteria; it never demotes criteria
that fail to discriminate between agents. A criterion every agent scores nearly
identically provides no gradient toward excellence (DR-Tulu / OpenRubrics:
rank/drop criteria by discriminative power = score spread across agents).

These tests cover the pure helpers in ``massgen/bootstrap_criteria.py``:
  - ``criterion_score_spread`` — population std-dev of each criterion across agents.
  - ``find_nondiscriminative_criteria`` — IDs whose spread is below a threshold,
    capped so a protected floor of criteria always survives.
  - ``demote_categories`` — reclassify given IDs to a softer category (so they no
    longer act as hard gates, but remain visible).
"""

from types import SimpleNamespace
from unittest.mock import patch

from massgen.bootstrap_criteria import (
    criterion_score_spread,
    demote_categories,
    find_nondiscriminative_criteria,
)
from massgen.orchestrator import Orchestrator


class TestCriterionScoreSpread:
    def test_spread_per_criterion(self):
        per_agent = {
            "agent1": {"E1": 9, "E2": 9},
            "agent2": {"E1": 9, "E2": 4},
        }
        spread = criterion_score_spread(per_agent)
        assert spread["E1"] == 0.0  # everyone agrees -> no discrimination
        assert spread["E2"] == 2.5  # pstdev([9, 4])

    def test_accepts_score_dicts_and_plain_numbers(self):
        per_agent = {
            "agent1": {"E1": {"score": 9}, "E2": 8},
            "agent2": {"E1": {"score": 5}, "E2": 8},
        }
        spread = criterion_score_spread(per_agent)
        assert spread["E1"] == 2.0  # pstdev([9, 5])
        assert spread["E2"] == 0.0

    def test_single_agent_yields_no_spread(self):
        spread = criterion_score_spread({"agent1": {"E1": 9}})
        assert spread == {}


class TestFindNondiscriminative:
    def test_flags_low_spread_criteria(self):
        per_agent = {
            "agent1": {"E1": 9, "E2": 9, "E3": 2},
            "agent2": {"E1": 9, "E2": 3, "E3": 8},
        }
        # E1 spread 0 (free-pass), E2 spread 3, E3 spread 3.
        result = find_nondiscriminative_criteria(per_agent, min_spread=0.75)
        assert result == ["E1"]

    def test_min_spread_threshold(self):
        # Three criteria so the floor (2) doesn't block pruning of one.
        per_agent = {
            "agent1": {"E1": 9, "E2": 9, "E3": 9},
            "agent2": {"E1": 8, "E2": 7, "E3": 3},
        }
        # E1 pstdev 0.5 (< 0.75 -> non-discriminative); E2 pstdev 1.0 and
        # E3 pstdev 3.0 (>= 0.75 -> keep).
        assert find_nondiscriminative_criteria(per_agent, min_spread=0.75) == ["E1"]

    def test_single_agent_prunes_nothing(self):
        per_agent = {"agent1": {"E1": 9, "E2": 1}}
        assert find_nondiscriminative_criteria(per_agent) == []

    def test_protect_floor_keeps_minimum_criteria(self):
        # All four criteria are non-discriminative (everyone identical).
        per_agent = {
            "agent1": {"E1": 9, "E2": 9, "E3": 9, "E4": 9},
            "agent2": {"E1": 9, "E2": 9, "E3": 9, "E4": 9},
        }
        result = find_nondiscriminative_criteria(per_agent, min_spread=0.75, protect_floor=2)
        # Never demote below the floor: at most total - floor == 2 may be pruned.
        assert len(result) == 2

    def test_no_pruning_when_at_or_below_floor(self):
        per_agent = {
            "agent1": {"E1": 9, "E2": 9},
            "agent2": {"E1": 9, "E2": 9},
        }
        assert find_nondiscriminative_criteria(per_agent, protect_floor=2) == []


class TestDemoteCategories:
    def test_demotes_only_named_ids(self):
        categories = {"E1": "primary", "E2": "standard", "E3": "primary"}
        out = demote_categories(categories, ["E1"])
        assert out["E1"] == "stretch"
        assert out["E2"] == "standard"
        assert out["E3"] == "primary"
        # original dict is not mutated
        assert categories["E1"] == "primary"

    def test_empty_ids_is_identity(self):
        categories = {"E1": "primary"}
        assert demote_categories(categories, []) == categories


class TestOrchestratorDemotionWiring:
    """End-to-end: _resolve_effective_checklist_criteria demotes free-pass criteria
    in bootstrap mode, and leaves them alone in static mode."""

    def _make_orch(self, criteria_mode):
        with patch.object(Orchestrator, "__init__", lambda self, **kw: None):
            orch = Orchestrator()
        orch.config = SimpleNamespace(
            coordination_config=SimpleNamespace(
                criteria_mode=criteria_mode,
                checklist_criteria_inline=["x"],
            ),
        )
        orch._bootstrap_criteria_accumulator = []
        orch._generated_evaluation_criteria = None
        orch._drain_pending_criteria_proposals = lambda: None
        orch._get_active_criteria = lambda agent_id: (
            ["c1", "c2", "c3"],
            {"E1": "primary", "E2": "primary", "E3": "standard"},
            None,
            None,
            None,
        )
        orch._get_decomposition_criteria_for_agent = lambda aid: None
        orch._is_changedoc_enabled = lambda: False
        # E1 spread 0 (free-pass); E2 spread 3; E3 spread 3.
        orch._last_per_agent_criterion_scores = {
            "agent1": {"E1": 9, "E2": 9, "E3": 2},
            "agent2": {"E1": 9, "E2": 3, "E3": 8},
        }
        return orch

    def test_bootstrap_mode_demotes_nondiscriminative(self):
        orch = self._make_orch("bootstrap_inline")
        _items, cats, _vby, _src, _anti, _anchors = orch._resolve_effective_checklist_criteria(agent_id="a")
        assert cats["E1"] == "stretch"  # free-pass -> demoted
        assert cats["E2"] == "primary"  # discriminative -> unchanged
        assert cats["E3"] == "standard"

    def test_static_mode_does_not_demote(self):
        orch = self._make_orch("static")
        _items, cats, _vby, _src, _anti, _anchors = orch._resolve_effective_checklist_criteria(agent_id="a")
        assert cats["E1"] == "primary"  # static mode -> no demotion
