"""Compact consensus map for the MassGen Textual TUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from massgen.events import EventType, MassGenEvent


def _agent_label(agent_id: str, index: int = 0) -> str:
    """Return a compact, stable display label for an agent."""
    if "_" in agent_id:
        suffix = agent_id.rsplit("_", 1)[-1]
        if suffix:
            return suffix[0].upper()
    for char in reversed(agent_id):
        if char.isalnum():
            return char.upper()
    return chr(ord("A") + index)


def _answer_label(label: Any) -> str:
    """Normalize answer labels for compact display."""
    raw = str(label or "").strip()
    if not raw:
        return ""
    if raw.startswith("agent"):
        return "A" + raw[len("agent") :]
    return raw


@dataclass
class ConsensusAgentState:
    """Display state for one agent in the consensus map."""

    agent_id: str
    label: str
    model: str = ""
    status: str = "idle"
    round_number: int = 1
    answer_label: str = ""
    voted_for: str | None = None
    voted_for_label: str = ""
    stopped: bool = False
    context_labels: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConsensusMapSnapshot:
    """Immutable render snapshot for the ConsensusMap widget."""

    visible: bool
    agents: dict[str, ConsensusAgentState]
    vote_counts: dict[str, int]
    leader_id: str | None = None
    winner_id: str | None = None
    phase: str = "idle"
    vote_summary: str = ""
    waiting_summary: str = ""


class ConsensusMapState:
    """Pure state reducer for the compact consensus map."""

    def __init__(
        self,
        agent_ids: list[str] | None = None,
        agent_models: dict[str, str] | None = None,
    ) -> None:
        self.reset_turn(agent_ids or [], agent_models or {})

    def reset_turn(
        self,
        agent_ids: list[str],
        agent_models: dict[str, str] | None = None,
    ) -> None:
        """Reset state for a new turn."""
        models = agent_models or {}
        self._agent_order = list(agent_ids)
        self._agents: dict[str, ConsensusAgentState] = {
            agent_id: ConsensusAgentState(
                agent_id=agent_id,
                label=_agent_label(agent_id, index),
                model=str(models.get(agent_id, "") or ""),
            )
            for index, agent_id in enumerate(self._agent_order)
        }
        self._winner_id: str | None = None
        self._phase = "idle"

    def set_agent_status(self, agent_id: str, status: str) -> None:
        """Set an agent's current activity status."""
        agent = self._agents.get(agent_id)
        if agent is not None:
            agent.status = status

    def apply_event(self, event: MassGenEvent) -> None:
        """Apply one structured coordination event."""
        event_type = event.event_type
        agent_id = event.agent_id or ""
        data = event.data or {}

        if event_type == EventType.PHASE_CHANGE:
            self._phase = str(data.get("phase") or self._phase)
            return

        if event_type in (
            EventType.ANSWER_SUBMITTED,
            EventType.VOTE,
            EventType.AGENT_STOPPED,
            EventType.AGENT_RESTART,
            EventType.CONTEXT_RECEIVED,
        ):
            if agent_id and agent_id not in self._agents:
                self._add_agent(agent_id)

        agent = self._agents.get(agent_id)

        if event_type == EventType.ANSWER_SUBMITTED and agent is not None:
            answer_label = _answer_label(data.get("answer_label"))
            if answer_label:
                agent.answer_label = answer_label
            agent.status = "answered"
            return

        if event_type == EventType.VOTE and agent is not None:
            target_id = str(data.get("target_id") or "")
            agent.voted_for = target_id or None
            agent.voted_for_label = _answer_label(data.get("voted_for_label"))
            agent.status = "voted"
            if target_id and target_id not in self._agents:
                self._add_agent(target_id)
            return

        if event_type == EventType.AGENT_STOPPED and agent is not None:
            agent.stopped = True
            agent.status = str(data.get("status") or "stopped")
            return

        if event_type == EventType.AGENT_RESTART and agent is not None:
            try:
                agent.round_number = max(
                    1,
                    int(data.get("restart_round") or agent.round_number),
                )
            except Exception:
                agent.round_number = max(1, agent.round_number)
            agent.status = "working"
            return

        if event_type == EventType.CONTEXT_RECEIVED and agent is not None:
            labels = data.get("context_labels")
            if isinstance(labels, list):
                agent.context_labels = [str(label) for label in labels]
            return

        if event_type in (
            EventType.WINNER_SELECTED,
            EventType.FINAL_PRESENTATION_START,
            EventType.PRESENTATION_START,
        ):
            if agent_id:
                if agent_id not in self._agents:
                    self._add_agent(agent_id)
                self._winner_id = agent_id
                self._agents[agent_id].status = "winner"
            self._phase = "presentation"

    def snapshot(self) -> ConsensusMapSnapshot:
        """Return a renderable snapshot."""
        vote_counts = self._vote_counts()
        leader_id = self._leader_id(vote_counts)
        votes = self._vote_summary()
        waiting = self._waiting_summary()
        return ConsensusMapSnapshot(
            visible=len(self._agents) > 1,
            agents={agent_id: self._agents[agent_id] for agent_id in self._agent_order if agent_id in self._agents},
            vote_counts=vote_counts,
            leader_id=leader_id,
            winner_id=self._winner_id,
            phase=self._phase,
            vote_summary=votes,
            waiting_summary=waiting,
        )

    def _add_agent(self, agent_id: str) -> None:
        self._agent_order.append(agent_id)
        self._agents[agent_id] = ConsensusAgentState(
            agent_id=agent_id,
            label=_agent_label(agent_id, len(self._agent_order) - 1),
        )

    def _vote_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for agent in self._agents.values():
            if agent.voted_for:
                counts[agent.voted_for] = counts.get(agent.voted_for, 0) + 1
        return counts

    @staticmethod
    def _leader_id(vote_counts: dict[str, int]) -> str | None:
        if not vote_counts:
            return None
        max_votes = max(vote_counts.values())
        leaders = [agent_id for agent_id, count in vote_counts.items() if count == max_votes]
        return leaders[0] if len(leaders) == 1 else None

    def _vote_summary(self) -> str:
        parts = []
        for agent_id in self._agent_order:
            agent = self._agents.get(agent_id)
            if not agent or not agent.voted_for:
                continue
            target = self._agents.get(agent.voted_for)
            target_label = target.label if target else _agent_label(agent.voted_for)
            parts.append(f"{agent.label}->{target_label}")
        return " ".join(parts)

    def _waiting_summary(self) -> str:
        waiting = []
        for agent_id in self._agent_order:
            agent = self._agents.get(agent_id)
            if not agent:
                continue
            if agent.status in {"voted", "winner", "done"} or agent.stopped:
                continue
            waiting.append(agent.label)
        return "Waiting: " + ", ".join(waiting) if waiting else ""


class ConsensusMap(Widget):
    """A compact visual summary of answer/vote convergence."""

    DEFAULT_CSS = ""

    _version = reactive(0)

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self._snapshot = ConsensusMapSnapshot(visible=False, agents={}, vote_counts={})
        self.add_class("hidden")

    def set_state(self, snapshot: ConsensusMapSnapshot) -> None:
        """Update the rendered snapshot."""
        self._snapshot = snapshot
        if snapshot.visible:
            self.remove_class("hidden")
        else:
            self.add_class("hidden")
        self._version += 1
        self.refresh()

    def render(self) -> Text:
        """Render a compact map with critical progress on the first line."""
        snap = self._snapshot
        text = Text()
        text.append("Consensus ", style="bold")

        if snap.winner_id:
            winner = snap.agents.get(snap.winner_id)
            if winner:
                text.append(f"{winner.label} wins", style="bold green")
            else:
                text.append("winner selected", style="bold green")
        elif snap.leader_id:
            leader = snap.agents.get(snap.leader_id)
            votes = snap.vote_counts.get(snap.leader_id, 0)
            if leader:
                text.append(f"{leader.label} leads {votes}", style="bold yellow")
        else:
            answered_count = self._answered_count(snap)
            if answered_count:
                plural = "" if answered_count == 1 else "s"
                text.append(f"{answered_count} answer{plural} in", style="green")
            else:
                text.append(self._phase_label(snap.phase), style="dim")

        if snap.agents:
            text.append("  |  ", style="dim")
        summary = self._agent_summary(snap)
        text.append(summary)

        details = Text()
        for index, agent in enumerate(snap.agents.values()):
            if index > 0:
                details.append("  ", style="dim")
            style = self._agent_style(agent, snap)
            answer = f" {agent.answer_label}" if agent.answer_label else ""
            suffix = ""
            if agent.stopped:
                suffix = " stop"
            elif agent.voted_for:
                target = snap.agents.get(agent.voted_for)
                target_label = target.label if target else _agent_label(agent.voted_for)
                suffix = f"->{target_label}"
            elif agent.status in {"working", "thinking", "streaming", "processing"}:
                suffix = " ..."
            details.append(f"{agent.label}{answer}{suffix}", style=style)

        if snap.vote_summary:
            details.append(f"  |  {snap.vote_summary}", style="cyan")
        elif snap.waiting_summary:
            details.append(f"  |  {snap.waiting_summary}", style="dim")

        if details.plain:
            text.append("\n")
            text.append(details)

        return text

    @staticmethod
    def _agent_summary(snapshot: ConsensusMapSnapshot) -> Text:
        summary = Text()
        for index, agent in enumerate(snapshot.agents.values()):
            if index > 0:
                summary.append("  ", style="dim")
            style = ConsensusMap._agent_style(agent, snapshot)
            label = f"{agent.label} {agent.answer_label}" if agent.answer_label else agent.label
            if agent.voted_for:
                target = snapshot.agents.get(agent.voted_for)
                target_label = target.label if target else _agent_label(agent.voted_for)
                label = f"{label}->{target_label}"
            elif agent.status in {"working", "thinking", "streaming", "processing"}:
                label = f"{label}..."
            summary.append(label, style=style)
        return summary

    @staticmethod
    def _answered_count(snapshot: ConsensusMapSnapshot) -> int:
        return sum(1 for agent in snapshot.agents.values() if agent.answer_label or agent.status in {"answered", "voted", "winner"})

    @staticmethod
    def _phase_label(phase: str) -> str:
        labels = {
            "idle": "getting ready",
            "coordinating": "comparing answers",
            "initial_answer": "drafting",
            "enforcement": "deciding",
            "presentation": "finalizing",
        }
        return labels.get(phase, phase.replace("_", " ") if phase else "getting ready")

    @staticmethod
    def _agent_style(agent: ConsensusAgentState, snapshot: ConsensusMapSnapshot) -> str:
        if snapshot.winner_id == agent.agent_id or agent.status == "winner":
            return "bold green"
        if snapshot.leader_id == agent.agent_id:
            return "bold yellow"
        if agent.status in {"voted", "answered", "complete"} or agent.stopped:
            return "green"
        if agent.status in {"error", "cancelled", "canceled"}:
            return "red"
        if agent.status in {"working", "thinking", "streaming", "processing"}:
            return "bold cyan"
        return "dim"
