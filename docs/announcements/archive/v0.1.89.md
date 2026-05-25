# MassGen v0.1.89 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.89 — Antigravity CLI Full Integration & Hardening! 🚀 This release completes the follow-up Antigravity integration pass: workflow-mode parity, early auth and binary health checks, reliable workspace writes via `--add-dir`, workspace-root `.antigravitycli/` anchoring, standalone `hooks.json` support, and prompt guardrails that hide subagent affordances when subagents are disabled.

## Install

```bash
pip install massgen==0.1.89
```

Antigravity CLI itself is installed separately:

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.89
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

## Posting Notes

- **Suggested image:** Use the full Antigravity integration graphic.
- **Fallback image:** If the full graphic is not ready, use a screenshot of the v0.1.89 release notes.

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.89 — Antigravity CLI Full Integration & Hardening! 🚀 This release completes the follow-up Antigravity integration pass: workflow-mode parity, early auth and binary health checks, reliable workspace writes via `--add-dir`, workspace-root `.antigravitycli/` anchoring, standalone `hooks.json` support, and prompt guardrails that hide subagent affordances when subagents are disabled.

**Key Improvements:**

🛰️ **Workflow-Mode Parity**:
- Antigravity now mirrors Gemini CLI's `new_answer` / `vote` workflow handling
- `vote` is hidden in no-answer rounds, keeping agents in `new_answer_only` mode when needed
- Post-evaluation prompts guard against stale `new_answer`, `vote`, or `stop` calls
- Duplicate parsed workflow calls are suppressed within a single turn

🧰 **Reliable Workspace Writes**:
- MassGen passes `--add-dir <cwd>` so agy's file tools write into the shared workspace
- A workspace-root `.antigravitycli/` marker anchors agy's project discovery
- `.antigravity/` and `.antigravitycli/` are treated as runtime artifacts

🔐 **Auth + Binary Health Checks**:
- The backend verifies `agy --version` before entering orchestration
- Runs fail fast when no `GEMINI_API_KEY`, `GOOGLE_API_KEY`, or cached Google OAuth credentials are available
- Docker mode continues to require API-key auth because OAuth state does not cross container boundaries

🔌 **Native Hooks**:
- Antigravity hooks now use standalone `hooks.json`
- `settings.json` enables hooks through `enableJsonHooks`
- The native hook adapter documents the Antigravity storage model separately from Gemini CLI

🧭 **Prompt Guardrails**:
- `TaskContextSection` only advertises `spawn_subagents` when subagents are actually enabled
- Multimodal-only runs keep `read_media` context guidance without leaking phantom subagent MCP affordances

🧪 **Tests**:
- `massgen/tests/test_antigravity_cli_backend.py` now covers health checks, authentication, workspace anchoring, `--add-dir`, hooks.json, workflow-mode filtering, duplicate tool-call suppression, multimodal prompt flattening, cancellation cleanup, and agent-id propagation
- `massgen/tests/test_system_prompt_sections.py` covers subagent affordance gating

**Getting Started:**

```bash
pip install massgen==0.1.89
curl -fsSL https://antigravity.google/cli/install.sh | bash
uv run massgen --config massgen/configs/features/fast_iteration_gemini_antigravity.yaml "Create an svg of an AI agent coding."
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.89

Feature highlights:

<!-- Paste feature-highlights.md content here -->
