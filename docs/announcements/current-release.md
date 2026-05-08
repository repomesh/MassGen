# MassGen v0.1.84 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.84 — TUI Consensus Map! 🚀 A new compact visual map below the agent status ribbon makes the physical shape of multi-agent collaboration visible at a glance — agent nodes, latest answers, vote arrows, leader, and winner — without replacing the timeline.

## Install

```bash
pip install massgen==0.1.84
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.84
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.84 — TUI Consensus Map! 🚀 A new compact visual map below the agent status ribbon makes the physical shape of multi-agent collaboration visible at a glance — agent nodes, latest answers, vote arrows, leader, and winner — without replacing the timeline.

**Key Improvements:**

🗺️ **TUI Consensus Map** — See coordination state at a glance:
- Compact map mounted below the agent status ribbon during multi-agent runs
- One node per agent with latest answer label, vote direction arrows, and current vote leader
- Winner state and waiting/working indicators surfaced visually
- Hidden on welcome screen and single-agent runs

⚡ **Event-Driven Updates** — Zero backend schema changes:
- Map state subscribes to existing structured coordination events (`answer_submitted`, `vote`, `agent_stopped`, `winner_selected`, `final_presentation_start`, `agent_restart`, `phase_change`, `context_received`)
- Direct-callback fallback path keeps the map accurate even when status/votes are pushed outside the unified event pipeline

📋 **OpenSpec-driven** — Full change proposal, scenarios, tasks, and validation under `openspec/changes/add-tui-consensus-map/`.

**Getting Started:**

```bash
pip install massgen==0.1.84
uv run massgen --config massgen/configs/basic/multi/gemini_gpt5_claude.yaml "Create an SVG of an AI agent coding."
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.84

Feature highlights:

<!-- Paste feature-highlights.md content here -->
