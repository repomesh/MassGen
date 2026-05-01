# MassGen v0.1.83 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.83 — In-Session Standalone Checkpoint MCP Integration! 🚀 The standalone checkpoint MCP server can now run *inside* a normal MassGen single-agent session, exposing the richer `init` + `checkpoint` tools backed by its own reviewer team.

## Install

```bash
pip install massgen==0.1.83
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.83
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.83 — In-Session Standalone Checkpoint MCP Integration! 🚀 The standalone checkpoint MCP server can now run *inside* a normal MassGen single-agent session, exposing the richer `init` + `checkpoint` tools backed by its own reviewer team.

**Key Improvements:**

🔌 **In-Session Standalone Checkpoint MCP** — The richer planning affordance, now in-session:
- Single-agent sessions can call the standalone server's `init` + `checkpoint` tools backed by their own reviewer team
- New `coordination.standalone_checkpoint` config block: `enabled`, `team_config`, `mode` (`generate` | `verify`), `single_checkpoint`, `include_workspace_context`
- Invalid `mode` values fall back to `generate` with a warning — typos surface instead of silently running the wrong mode
- Multi-agent parents skip the standalone server with a warning (the standalone server runs its own reviewer panel)

🎴 **Enhanced Checkpoint Tool Card** — TUI tool card visualization distinguishes primary checkpoint operations from system tasks with improved context and result display

📦 **Example Configs** — Runnable in-session standalone checkpoint setups:
- `massgen/configs/checkpoint/standalone_mcp/fast_iteration.yaml`
- `massgen/configs/checkpoint/standalone_mcp/reviewers.yaml`

**Getting Started:**

```bash
pip install massgen==0.1.83
uv run massgen --config @examples/checkpoint/standalone_mcp/fast_iteration.yaml "Plan a refactor of the auth module."
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.83

Feature highlights:

<!-- Paste feature-highlights.md content here -->
