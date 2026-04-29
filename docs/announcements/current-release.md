# MassGen v0.1.82 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.82 — TUI Copy Mode & Checkpoint Quality Improvements! 🚀 A new `Ctrl+Shift+S` copy mode lets you drag-select text natively in the terminal UI, and the standalone checkpoint MCP server gets stronger plan quality criteria and agent recovery guidance.

## Install

```bash
pip install massgen==0.1.82
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.82
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.82 — TUI Copy Mode & Checkpoint Quality Improvements! 🚀 A new `Ctrl+Shift+S` copy mode lets you drag-select text natively in the terminal UI, and the standalone checkpoint MCP server gets stronger plan quality criteria and agent recovery guidance.

**Key Improvements:**

📋 **TUI Copy Mode** — Select and copy terminal output natively:
- Press `Ctrl+Shift+S` to release mouse tracking — drag to select text, then copy with your terminal's shortcut
- Press again to restore Textual's normal mouse behavior
- Auto-restores mouse capture if you exit while copy mode is active

🔒 **Checkpoint Quality Improvements** — Smarter, safer checkpoint plans:
- New `include_workspace_context` config option mounts the executor's workspace as read-only context for reviewer agents (default off)
- Mode-aware plan quality criteria score selective branch depth and fallback handling (single vs. multi-checkpoint)
- Single-checkpoint agent recovery workflow: detailed steps for when a plan branch resolves to `terminate` — find safe alternates before giving up
- Extended "better means" safety guidance with four axes for recognizing when a cheaper path becomes unsafe

🖥️ **TUI Visual Polish** — Ribbon dividers changed from `│` to `·` for a cleaner look

**Getting Started:**

```bash
pip install massgen==0.1.82
uv run massgen --config @examples/features/fast_iteration.yaml "Create an svg of an AI agent coding."
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.82

Feature highlights:

<!-- Paste feature-highlights.md content here -->
