# 🚀 Release Highlights — v0.1.83 (2026-05-01)

### 🔌 [In-Session Standalone Checkpoint MCP Integration](https://docs.massgen.ai/en/latest/user_guide/checkpoint.html)
- **In-session standalone checkpoint** ([#1079](https://github.com/massgen/MassGen/pull/1079)): The standalone checkpoint MCP server (originally for external hosts like Claude Code) can now be exposed *inside* a normal MassGen run, so a single-agent session can call its richer `init` + `checkpoint` tools backed by its own reviewer team
- **`coordination.standalone_checkpoint` config block** ([#1079](https://github.com/massgen/MassGen/pull/1079)): New YAML block with `enabled`, `team_config`, `mode` (`generate` | `verify`), `single_checkpoint`, `include_workspace_context`; invalid `mode` values fall back to `generate` with a warning
- **Single-agent-only affordance gating**: Multi-agent parents skip the standalone server with a warning — the standalone server runs its own reviewer panel
- **Enhanced checkpoint tool card** ([#1079](https://github.com/massgen/MassGen/pull/1079)): TUI tool card visualization distinguishes primary checkpoint operations from system tasks with improved context and result display

### 📦 New Example Configs
- `massgen/configs/checkpoint/standalone_mcp/fast_iteration.yaml` — fast-iteration single-agent run with in-session standalone checkpoint
- `massgen/configs/checkpoint/standalone_mcp/reviewers.yaml` — reviewer team config for the standalone server

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  pip install massgen==0.1.83
  uv run massgen --config @examples/checkpoint/standalone_mcp/fast_iteration.yaml "Plan a refactor of the auth module."
  ```
