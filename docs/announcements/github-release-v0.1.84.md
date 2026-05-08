# 🚀 Release Highlights — v0.1.84 (2026-05-08)

### 🗺️ [TUI Consensus Map](https://docs.massgen.ai/en/latest/user_guide/tui.html)
- **Compact visual map** ([#1085](https://github.com/massgen/MassGen/pull/1085)): A new strip below the agent status ribbon during multi-agent runs that summarizes coordination state without replacing the timeline
- **Per-agent state**: One node per agent with latest answer label, vote direction arrows, current vote leader, winner state, and waiting/working indicators
- **Visibility logic**: Hidden on welcome screen and single-agent runs — only shown when more than one active agent is coordinating

### ⚡ Event-Driven, No Backend Changes
- **Existing event pipeline** ([#1085](https://github.com/massgen/MassGen/pull/1085)): Map state subscribes to `answer_submitted`, `vote`, `agent_stopped`, `winner_selected`, `final_presentation_start`, `agent_restart`, `phase_change`, and `context_received`
- **Direct-callback fallback** ([#1085](https://github.com/massgen/MassGen/pull/1085)): Map remains accurate when direct TUI callbacks update agent status or votes outside the unified event pipeline

### 📋 OpenSpec Coverage
- Full change proposal, scenarios, tasks, and validation under `openspec/changes/add-tui-consensus-map/`

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  pip install massgen==0.1.84
  uv run massgen --config massgen/configs/basic/multi/gemini_gpt5_claude.yaml "Create an SVG of an AI agent coding."
  ```
