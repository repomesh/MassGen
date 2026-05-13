# 🚀 Release Highlights — v0.1.86 (2026-05-13)

### 🧠 `bootstrap_subagent` Discriminator Is Now Functional
- `orchestrator.coordination.criteria_mode: bootstrap_subagent` now runs a between-rounds LLM critic via `SubagentManager`
- The critic reads the task and each agent's latest answer, emits `proposed_criteria` as JSON, and the orchestrator merges them into `bootstrap_criteria_accumulator.json`
- The next round's checklist is augmented automatically, giving the same end state as `bootstrap_inline` but with criteria sourced from a dedicated critic rather than the answering agents
- The discriminator runs once per unique answer snapshot so unchanged rounds are not re-critiqued

### 🧹 Session-End Criteria Drain
- `Orchestrator._drain_at_session_end` forces one final drain before final presentation
- Late stdio JSONL emissions are captured instead of being stranded after the last checklist resolution pass

### 🛠️ Codex MCP Approval Fix
- `codex exec` workspaces now get both non-interactive approval bypasses:
  - `approval_policy = "never"`
  - Per-MCP-server `default_tools_approval_mode = "approve"`
- This prevents external MCP tools such as `submit_checklist`, `create_task_plan`, `new_answer`, and `read_media` from failing immediately with "user cancelled MCP tool call"

### 🧪 Tests
- `massgen/tests/test_bootstrap_criteria.py` expanded to 35 tests for discriminator behavior and session-end drain
- `massgen/tests/test_codex_native_hook_adapter.py::TestCodexWorkspaceApprovalPolicy` covers Codex approval config across modes

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  pip install massgen==0.1.86
  uv run massgen --config massgen/configs/coordination/bootstrap_subagent_criteria.yaml "Create an SVG of an AI agent coding."
  ```
- Inspect emerging criteria at `.massgen/massgen_logs/<session>/bootstrap_criteria_accumulator.json`
