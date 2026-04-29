# 🚀 Release Highlights — v0.1.82 (2026-04-29)

### 📋 [TUI Copy Mode](https://docs.massgen.ai/en/latest/user_guide/tui.html)
- **Copy Mode toggle** ([#1076](https://github.com/massgen/MassGen/pull/1076)): Press `Ctrl+Shift+S` to release terminal mouse tracking — drag to select text, copy with your terminal's built-in shortcut, press again to restore Textual's mouse behavior
- **Auto-restore on exit**: Mouse tracking is correctly restored before the driver tears down if you exit while copy mode is active
- **Visual banner**: A banner appears in the input area when copy mode is active

### 🔒 [Checkpoint Standalone Improvements](https://docs.massgen.ai/en/latest/user_guide/checkpoint.html)
- **Workspace context option** ([#1076](https://github.com/massgen/MassGen/pull/1076)): New `include_workspace_context` config field for the standalone checkpoint MCP server — optionally mounts the executor's workspace as read-only context for reviewer agents (default `false`)
- **Plan quality criteria** ([#1076](https://github.com/massgen/MassGen/pull/1076)): Mode-aware quality criteria score selective branch depth and fallback handling in single vs. multi-checkpoint modes
- **Agent recovery guidance** ([#1076](https://github.com/massgen/MassGen/pull/1076)): Single-checkpoint continuation workflow in `checkpoint_instructions.md` — detailed steps for when a plan branch resolves to `terminate`
- **"Better means" safety axes**: Four generalized axes in the checkpoint planning prompt for recognizing when a cheaper path becomes unsafe (scarcity/contention, external visibility, authority substitution, scope expansion)

### 🖥️ TUI Visual Polish
- **Ribbon dividers** ([#1076](https://github.com/massgen/MassGen/pull/1076)): Changed from `│` (pipe) to `·` (dot) for a cleaner, lighter agent status ribbon

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  pip install massgen==0.1.82
  uv run massgen --config @examples/features/fast_iteration.yaml "Create an svg of an AI agent coding."
  ```
