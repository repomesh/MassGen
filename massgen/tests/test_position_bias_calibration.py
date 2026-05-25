"""Position-bias / self-preference calibration for checklist evaluation (Pillar 3).

These tests cover two defects found in the evaluation path:

1. **Tie-break determinism** — ``_extract_flat_scores`` in
   ``massgen/mcp_tools/checklist_tools_server.py`` selected the "best" agent with
   ``if total > best_total``, so equal-total agents were broken by dict iteration
   order (whoever appeared first won). The verdict aggregation must be independent
   of submission/iteration order.

2. **Presentation-order counterbalancing** — ``format_current_answers_with_summaries``
   in ``massgen/message_templates.py`` iterated candidates in dict *insertion order*,
   so whichever candidate landed first got the primacy slot every round. With an
   ``order_seed`` the formatter must counterbalance (rotate) the presentation order
   while keeping each anonymous label attached to its own content, so score
   attribution is unaffected.

Design decisions (approved):
  - Counterbalanced permutation = deterministic left-rotation by ``order_seed`` over
    the label-sorted candidate list (reproducible, varies per round/agent).
  - ``order_seed=None`` preserves the legacy insertion-order behavior (additive change).
  - Tie-break rule: on equal aggregate score, the lexicographically-smallest label wins.
"""

from massgen.mcp_tools.checklist_tools_server import _extract_flat_scores
from massgen.message_templates import MessageTemplates


def _score(n: int) -> dict:
    return {"score": n, "reasoning": "x"}


class TestTieBreakDeterminism:
    """Defect 1: best-agent selection must not depend on iteration/insertion order."""

    def test_tie_is_broken_independent_of_insertion_order(self):
        # agent1 and agent2 have identical aggregate totals (9 + 5 == 5 + 9).
        order_a = {
            "agent1": {"E1": _score(9), "E2": _score(5)},
            "agent2": {"E1": _score(5), "E2": _score(9)},
        }
        order_b = {
            "agent2": {"E1": _score(5), "E2": _score(9)},
            "agent1": {"E1": _score(9), "E2": _score(5)},
        }
        best_a, _, _ = _extract_flat_scores(order_a, item_prefix="E", n_items=2)
        best_b, _, _ = _extract_flat_scores(order_b, item_prefix="E", n_items=2)
        assert best_a == best_b, "tie-break must be independent of insertion order"
        # Deterministic rule: lexicographically-smallest label wins the tie.
        assert best_a == "agent1"

    def test_strict_winner_still_selected(self):
        scores = {
            "agent1": {"E1": _score(9), "E2": _score(5)},  # total 14
            "agent2": {"E1": _score(7), "E2": _score(8)},  # total 15
        }
        best, _, _ = _extract_flat_scores(scores, item_prefix="E", n_items=2)
        assert best == "agent2"


class TestPresentationOrderCounterbalancing:
    """Defect 2: presentation order must counterbalance with order_seed."""

    summaries = {"agent_a": "AAA", "agent_b": "BBB", "agent_c": "CCC"}
    mapping = {"agent_a": "agent1", "agent_b": "agent2", "agent_c": "agent3"}

    def _first_label(self, text: str) -> str:
        # The first candidate block after the header determines the primacy slot.
        body = text.split("<CURRENT ANSWERS from the agents>", 1)[1]
        positions = {lbl: body.find(f"<{lbl}>") for lbl in ("agent1", "agent2", "agent3")}
        return min(positions, key=positions.get)

    def test_rotation_moves_primacy_slot(self):
        mt = MessageTemplates()
        first_at_seed = {}
        for seed in range(3):
            out = mt.format_current_answers_with_summaries(
                self.summaries,
                self.mapping,
                order_seed=seed,
            )
            first_at_seed[seed] = self._first_label(out)
        # Each seed should put a different label in the primacy slot (full rotation).
        assert len(set(first_at_seed.values())) == 3, first_at_seed
        assert first_at_seed[0] == "agent1"
        assert first_at_seed[1] == "agent2"
        assert first_at_seed[2] == "agent3"

    def test_seed_wraps_modulo_count(self):
        mt = MessageTemplates()
        out0 = mt.format_current_answers_with_summaries(self.summaries, self.mapping, order_seed=0)
        out3 = mt.format_current_answers_with_summaries(self.summaries, self.mapping, order_seed=3)
        assert out0 == out3, "order_seed should rotate modulo candidate count"

    def test_order_independent_of_insertion_order(self):
        mt = MessageTemplates()
        reversed_summaries = {"agent_c": "CCC", "agent_b": "BBB", "agent_a": "AAA"}
        out1 = mt.format_current_answers_with_summaries(self.summaries, self.mapping, order_seed=1)
        out2 = mt.format_current_answers_with_summaries(reversed_summaries, self.mapping, order_seed=1)
        assert out1 == out2, "same seed must yield same output regardless of dict insertion order"

    def test_labels_travel_with_content(self):
        # After any rotation, each anonymous label must still wrap its OWN summary.
        mt = MessageTemplates()
        for seed in range(3):
            out = mt.format_current_answers_with_summaries(self.summaries, self.mapping, order_seed=seed)
            assert "<agent1> AAA <end of agent1>" in out
            assert "<agent2> BBB <end of agent2>" in out
            assert "<agent3> CCC <end of agent3>" in out

    def test_default_seed_none_preserves_insertion_order(self):
        # Backward compat: without a seed, legacy insertion-order behavior is kept.
        mt = MessageTemplates()
        insertion = {"agent_b": "BBB", "agent_a": "AAA"}
        mapping = {"agent_a": "agent1", "agent_b": "agent2"}
        out = mt.format_current_answers_with_summaries(insertion, mapping)
        assert out.index("<agent2>") < out.index("<agent1>"), "None seed keeps insertion order"


class TestOrderSeedWiring:
    """The seed must survive the full builder chain (orchestrator -> formatter)."""

    summaries = {"agent_a": "AAA", "agent_b": "BBB", "agent_c": "CCC"}
    mapping = {"agent_a": "agent1", "agent_b": "agent2", "agent_c": "agent3"}

    def _first_label(self, user_message: str) -> str:
        body = user_message.split("<CURRENT ANSWERS from the agents>", 1)[1]
        positions = {lbl: body.find(f"<{lbl}>") for lbl in ("agent1", "agent2", "agent3")}
        return min(positions, key=positions.get)

    def test_build_initial_conversation_threads_seed(self):
        mt = MessageTemplates()
        conv = mt.build_initial_conversation(
            task="t",
            agent_summaries=self.summaries,
            agent_mapping=self.mapping,
            order_seed=1,
        )
        assert self._first_label(conv["user_message"]) == "agent2"

    def test_build_conversation_with_context_threads_seed(self):
        mt = MessageTemplates()
        conv = mt.build_conversation_with_context(
            current_task="t",
            agent_summaries=self.summaries,
            agent_mapping=self.mapping,
            order_seed=2,
        )
        assert self._first_label(conv["user_message"]) == "agent3"


class TestOwnLastOrderSeed:
    """compute_own_last_order_seed must place the scoring agent's own answer LAST,
    derived from the answering subset (not the global roster) so it stays correct
    when only a non-contiguous subset has answered."""

    mapping = {"agent_a": "agent1", "agent_b": "agent2", "agent_c": "agent3"}

    def _own_block_is_last(self, summaries, agent_id, mapping):
        mt = MessageTemplates()
        seed = MessageTemplates.compute_own_last_order_seed(agent_id, list(summaries.keys()), mapping)
        out = mt.format_current_answers_with_summaries(summaries, mapping, order_seed=seed)
        body = out.split("<CURRENT ANSWERS from the agents>", 1)[1]
        own_label = mapping[agent_id]
        own_pos = body.find(f"<{own_label}>")
        others = [body.find(f"<{lbl}>") for aid, lbl in mapping.items() if aid in summaries and aid != agent_id]
        return all(own_pos > p for p in others)

    def test_full_roster_each_agent_sees_own_answer_last(self):
        summaries = {"agent_a": "A", "agent_b": "B", "agent_c": "C"}
        for aid in summaries:
            assert self._own_block_is_last(summaries, aid, self.mapping), aid

    def test_noncontiguous_subset_still_places_own_last(self):
        # Only agent_a and agent_c have answered; agent_b has not. This is the case
        # the global-label seed got WRONG (agent3's own answer landed first).
        summaries = {"agent_a": "A", "agent_c": "C"}
        assert self._own_block_is_last(summaries, "agent_c", self.mapping)
        assert self._own_block_is_last(summaries, "agent_a", self.mapping)

    def test_seed_independent_of_answer_dict_order(self):
        s1 = {"agent_a": "A", "agent_c": "C"}
        s2 = {"agent_c": "C", "agent_a": "A"}
        assert MessageTemplates.compute_own_last_order_seed("agent_c", list(s1), self.mapping) == MessageTemplates.compute_own_last_order_seed("agent_c", list(s2), self.mapping)

    def test_agent_not_in_answer_set_falls_back_to_label_index(self):
        # Scoring agent hasn't answered -> no own answer to place last; falls back
        # to its anonymous-label index for general counterbalancing.
        summaries = {"agent_a": "A", "agent_b": "B"}
        seed = MessageTemplates.compute_own_last_order_seed("agent_c", list(summaries), self.mapping)
        assert seed == 3  # agent3's label index
