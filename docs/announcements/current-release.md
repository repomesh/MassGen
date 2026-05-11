# MassGen v0.1.85 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.85 — Discriminative Criteria Emergence (`criteria_mode`)! 🚀 Evaluation criteria can now emerge from observed gaps across rounds instead of being pre-authored — agents propose what a stronger answer would satisfy, the accumulator dedupes and caps, and the next round's checklist is augmented automatically. Anti-Goodhart by construction.

> ⚠️ **First-stage release — work in progress.** This is the initial drop of `criteria_mode`. The `bootstrap_inline` variant is fully wired and the accumulator/propagation path is end-to-end tested, but the feature is still maturing — expect further finalization and more thorough end-to-end testing (especially around `bootstrap_subagent`'s LLM discriminator) in v0.1.86.

## Install

```bash
pip install massgen==0.1.85
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.85
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.85 — Discriminative Criteria Emergence (`criteria_mode`)! 🚀 Evaluation criteria can now emerge from observed gaps across rounds instead of being pre-authored — agents propose what a stronger answer would satisfy, the accumulator dedupes and caps, and the next round's checklist is augmented automatically.

> ⚠️ **First-stage release — work in progress.** `bootstrap_inline` is fully wired across SDK and stdio backends and the accumulator is end-to-end tested, but the feature is still maturing. Expect finalization and more thorough end-to-end testing in v0.1.86, where the `bootstrap_subagent` LLM discriminator also lands.

**Key Improvements:**

🧪 **`bootstrap_inline` (fully functional)** — Self-discriminative criteria across all backends:
- Each agent emits a short `proposed_criteria` list alongside its `submit_checklist` call — criteria a stronger answer would satisfy that the current answers do *not*
- Proposals are deduped by exact text and FIFO-capped (`bootstrap_max_total`, default 30)
- Persisted to `bootstrap_criteria_accumulator.json` in the session log dir
- SDK (Claude Code) wires the field directly into the in-process tool schema; stdio backends (gemini, codex, response, chat_completions, claude, grok) emit through `proposed_criteria.jsonl` drained by the orchestrator

🛠️ **`bootstrap_subagent` (wired, LLM step queued for v0.1.86)** — Critic-driven variant:
- Same accumulator pipeline, but criteria come from a between-rounds critic rather than the answering agents
- LLM discriminator pass is the v0.1.86 follow-up

🛡️ **Anti-Goodhart by Construction** — Criteria come from observed gaps, not priors that may not match the task. Removes a cold-start friction: users no longer need to pre-author criteria for new tasks.

📦 **New Configs**:
- `massgen/configs/coordination/bootstrap_inline_criteria.yaml`
- `massgen/configs/coordination/bootstrap_subagent_criteria.yaml`

**Getting Started:**

```bash
pip install massgen==0.1.85
uv run massgen --config massgen/configs/coordination/bootstrap_inline_criteria.yaml "Create an SVG of an AI agent coding."
```

Inspect the emerging criteria at `.massgen/massgen_logs/<session>/bootstrap_criteria_accumulator.json`.

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.85

Feature highlights:

<!-- Paste feature-highlights.md content here -->
