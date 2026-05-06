from __future__ import annotations

from textual.app import App, ComposeResult

from massgen.events import EventType, MassGenEvent
from massgen.frontend.displays.textual_widgets.consensus_map import (
    ConsensusMap,
    ConsensusMapState,
)


def test_consensus_map_state_tracks_answers_votes_and_winner() -> None:
    state = ConsensusMapState(
        ["agent_a", "agent_b", "agent_c"],
        {"agent_a": "claude", "agent_b": "gpt", "agent_c": "gemini"},
    )

    state.apply_event(
        MassGenEvent.create(
            EventType.ANSWER_SUBMITTED,
            agent_id="agent_a",
            answer_label="agent1.1",
            answer_number=1,
            content="A",
        ),
    )
    state.apply_event(
        MassGenEvent.create(
            EventType.ANSWER_SUBMITTED,
            agent_id="agent_b",
            answer_label="agent2.1",
            answer_number=1,
            content="B",
        ),
    )
    state.apply_event(
        MassGenEvent.create(
            EventType.VOTE,
            agent_id="agent_c",
            target_id="agent_b",
            reason="best",
            voted_for_label="agent2.1",
        ),
    )
    state.apply_event(
        MassGenEvent.create(
            EventType.WINNER_SELECTED,
            agent_id="agent_b",
            vote_results={"winner": "agent_b"},
        ),
    )

    snapshot = state.snapshot()

    assert snapshot.visible is True
    assert snapshot.agents["agent_a"].answer_label == "A1.1"
    assert snapshot.agents["agent_b"].answer_label == "A2.1"
    assert snapshot.agents["agent_c"].voted_for == "agent_b"
    assert snapshot.leader_id == "agent_b"
    assert snapshot.winner_id == "agent_b"
    assert "C->B" in snapshot.vote_summary


def test_consensus_map_state_hides_for_single_agent_and_resets() -> None:
    state = ConsensusMapState(["agent_a"], {"agent_a": "claude"})

    assert state.snapshot().visible is False

    state.reset_turn(["agent_a", "agent_b"], {"agent_a": "claude", "agent_b": "gpt"})
    state.set_agent_status("agent_a", "working")
    state.apply_event(
        MassGenEvent.create(
            EventType.AGENT_RESTART,
            agent_id="agent_a",
            restart_round=2,
            restart_reason="new answer",
        ),
    )

    snapshot = state.snapshot()

    assert snapshot.visible is True
    assert snapshot.agents["agent_a"].round_number == 2
    assert snapshot.agents["agent_a"].status == "working"


def test_consensus_map_state_keeps_answer_label_when_tool_fallback_arrives() -> None:
    state = ConsensusMapState(
        ["agent_a", "agent_b"],
        {"agent_a": "claude", "agent_b": "gpt"},
    )
    state.apply_event(
        MassGenEvent.create(
            EventType.ANSWER_SUBMITTED,
            agent_id="agent_a",
            answer_label="agent1.1",
            answer_number=1,
            content="answer",
        ),
    )

    state.apply_event(
        MassGenEvent.create(
            EventType.ANSWER_SUBMITTED,
            agent_id="agent_a",
            answer_number=1,
            content="",
        ),
    )

    assert state.snapshot().agents["agent_a"].answer_label == "A1.1"


def test_consensus_map_widget_promotes_answer_progress_to_first_line() -> None:
    state = ConsensusMapState(
        ["agent_a", "agent_b"],
        {"agent_a": "claude", "agent_b": "gpt"},
    )
    state.apply_event(
        MassGenEvent.create(
            EventType.ANSWER_SUBMITTED,
            agent_id="agent_a",
            answer_label="agent1.1",
            answer_number=1,
            content="answer",
        ),
    )
    widget = ConsensusMap(id="consensus_map")
    widget.set_state(state.snapshot())

    first_line = widget.render().plain.splitlines()[0]

    assert "getting ready" not in first_line
    assert "1 answer in" in first_line
    assert "A A1.1" in first_line


class _ConsensusMapApp(App):
    def compose(self) -> ComposeResult:
        self.state = ConsensusMapState(
            ["agent_a", "agent_b"],
            {"agent_a": "claude", "agent_b": "gpt"},
        )
        self.state.apply_event(
            MassGenEvent.create(
                EventType.ANSWER_SUBMITTED,
                agent_id="agent_a",
                answer_label="agent1.1",
                answer_number=1,
                content="answer",
            ),
        )
        self.state.apply_event(
            MassGenEvent.create(
                EventType.VOTE,
                agent_id="agent_b",
                target_id="agent_a",
                reason="best",
                voted_for_label="agent1.1",
            ),
        )
        widget = ConsensusMap(id="consensus_map")
        widget.set_state(self.state.snapshot())
        yield widget


async def test_consensus_map_widget_renders_compact_state() -> None:
    app = _ConsensusMapApp()
    async with app.run_test(size=(100, 12)) as pilot:
        widget = pilot.app.query_one(ConsensusMap)
        text = widget.render().plain

    assert "Consensus" in text
    assert "A A1.1" in text
    assert "B->A" in text
