# MassGen v0.1.86 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.86 — `bootstrap_subagent` Discriminator + Codex MCP Approval Fix! 🚀 The critic-driven criteria path is now functional: MassGen can run an in-process LLM discriminator between rounds, propose stronger evaluation criteria from the current answers, merge them into the accumulator, and augment the next round's checklist automatically.

This release also fixes Codex MCP tool calls under `codex exec` so checklist/workflow tools no longer fail immediately with "user cancelled MCP tool call" in non-interactive runs.

## Install

```bash
pip install massgen==0.1.86
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.86
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.86 — `bootstrap_subagent` Discriminator + Codex MCP Approval Fix! 🚀 The critic-driven criteria path is now functional: MassGen can run an in-process LLM discriminator between rounds, propose stronger evaluation criteria from the current answers, merge them into the accumulator, and augment the next round's checklist automatically.

**Key Improvements:**

🧠 **`bootstrap_subagent` is now functional** — Dedicated critic-driven criteria emergence:
- `criteria_mode: bootstrap_subagent` runs a between-rounds LLM critic via `SubagentManager`
- The critic reads the task and each agent's latest answer, then emits `proposed_criteria` as JSON
- The orchestrator merges those criteria into `bootstrap_criteria_accumulator.json`
- The next round's checklist is augmented without asking answering agents to propose criteria themselves
- The discriminator runs once per unique answer snapshot, avoiding repeated critiques of unchanged rounds

🧹 **Session-end drain** — Late stdio emissions are captured before final presentation, so criteria proposed near the end of a run are not stranded after the final checklist resolution pass.

🛠️ **Codex MCP approval fix** — `codex exec` workspaces now get both approval bypasses needed for non-interactive external MCP calls:
- Top-level `approval_policy = "never"`
- Per-MCP-server `default_tools_approval_mode = "approve"`

🧪 **Tests**:
- Expanded bootstrap criteria coverage to 35 tests
- Added Codex workspace approval policy coverage for all approval modes

**Getting Started:**

```bash
pip install massgen==0.1.86
uv run massgen --config massgen/configs/coordination/bootstrap_subagent_criteria.yaml "Create an SVG of an AI agent coding."
```

Inspect the emerging criteria at `.massgen/massgen_logs/<session>/bootstrap_criteria_accumulator.json`.

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.86

Feature highlights:

<!-- Paste feature-highlights.md content here -->
