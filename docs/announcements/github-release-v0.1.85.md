# 🚀 Release Highlights — v0.1.85 (2026-05-11)

> ⚠️ **First-stage release — still maturing.** Expect further finalization and more thorough end-to-end testing in v0.1.86.

### 🧪 Discriminative Criteria Emergence (`criteria_mode`)
- **`bootstrap_inline` variant (fully functional)**: New `orchestrator.coordination.criteria_mode: bootstrap_inline` makes each agent emit a short `proposed_criteria` list alongside its `submit_checklist` call — criteria a stronger answer would satisfy that the current answers do *not*. Proposals are deduped, FIFO-capped (`bootstrap_max_total`, default 30), persisted to `bootstrap_criteria_accumulator.json`, and merged into the next round's checklist via the existing `EvaluationSection`
- **All backends with checklist tool support**: SDK path (Claude Code) gets the field directly in the in-process tool schema; stdio backends (gemini, codex, response, chat_completions, claude, grok) get a JSONL emission channel — `proposed_criteria.jsonl` next to checklist specs, drained by the orchestrator each pass
- **`bootstrap_subagent` variant (wired, LLM step deferred)**: Same accumulator pipeline; in-process LLM discriminator pass queued for v0.1.86
- **New module** `massgen/bootstrap_criteria.py` with `merge_proposals`, `augment_with_accumulator`, `is_bootstrap_mode`, `validate_criteria_mode`
- **Config fields**: `CoordinationConfig.{criteria_mode, bootstrap_max_per_agent_per_round, bootstrap_max_total}`

### 🛡️ Anti-Goodhart by Construction
- Criteria come from observed gaps, not priors that may not match the task
- Removes cold-start friction: users no longer need to pre-author criteria for new tasks — the first round produces both answers *and* the criteria the second round must rise to

### 📦 New Example Configs
- `massgen/configs/coordination/bootstrap_inline_criteria.yaml` — fully functional variant
- `massgen/configs/coordination/bootstrap_subagent_criteria.yaml` — accumulator wired, LLM step in v0.1.86

### 🧪 Tests
- 30 new tests in `massgen/tests/test_bootstrap_criteria.py` (476 lines) covering merge/dedup/cap, config validation, `AgentState.criteria_proposals`, augmentation across criteria sources, rendering gating, and round-N → round-N+1 propagation end-to-end

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  pip install massgen==0.1.85
  uv run massgen --config massgen/configs/coordination/bootstrap_inline_criteria.yaml "Create an SVG of an AI agent coding."
  ```
- Inspect the emerging criteria at `.massgen/massgen_logs/<session>/bootstrap_criteria_accumulator.json`
