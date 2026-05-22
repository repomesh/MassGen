# MassGen v0.1.88 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.88 — Antigravity CLI Backend! 🚀 This is the first version of MassGen's Antigravity integration: MassGen can now run Google's Antigravity CLI (`agy`) as a first-class backend, with workspace-local config isolation, Antigravity-compatible MCP config generation, native hook adapter support, and new single-agent and mixed Gemini + Antigravity example configs. We plan to complete the full integration in the next release.

## Install

```bash
pip install massgen==0.1.88
```

Antigravity CLI itself is installed separately:

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.88
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

## Posting Notes

- **Suggested image:** Use a screenshot of the v0.1.88 release notes.
- **Visual plan:** Save the full Antigravity integration graphic for the next release, when the full integration lands.

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.88 — Antigravity CLI Backend! 🚀 This is the first version of MassGen's Antigravity integration: MassGen can now run Google's Antigravity CLI (`agy`) as a first-class backend, with workspace-local config isolation, Antigravity-compatible MCP config generation, native hook adapter support, and new single-agent and mixed Gemini + Antigravity example configs. We plan to complete the full integration in the next release.

**Key Improvements:**

🛰️ **Antigravity CLI Backend** — New `antigravity_cli` backend:
- Wraps Google's `agy` binary as a MassGen agent backend
- Accepts OAuth state from `~/.gemini/google_accounts.json` or `GEMINI_API_KEY` / `GOOGLE_API_KEY`
- Treats the configured `model` value as informational because Antigravity selects the active model server-side
- Supports local and Docker execution, with Docker requiring API-key auth

🧰 **Workspace-Local Isolation** — Antigravity project state stays inside the run:
- MassGen passes `--gemini_dir <workspace>/.antigravity`
- MCP config and settings are written under `.antigravity/`
- User-global `~/.gemini/` config is not mutated

🔌 **MCP + Hook Integration**:
- MassGen MCP server entries are translated into Antigravity's `mcp_config.json` schema
- HTTP MCP servers use Antigravity's `serverUrl` field
- `AntigravityCLINativeHookAdapter` reuses Gemini CLI hook behavior for Antigravity's compatible hook protocol

📦 **New Configs**:
- `massgen/configs/providers/antigravity/antigravity_cli_local.yaml`
- `massgen/configs/features/fast_iteration_gemini_antigravity.yaml`

🧪 **Tests**:
- `massgen/tests/test_antigravity_cli_backend.py` covers binary discovery, command construction, workspace-local config, MCP schema, provider metadata, stdout/error streaming, workflow JSON envelopes, Docker/API-key constraints, hook wiring, and env passthrough

**Getting Started:**

```bash
pip install massgen==0.1.88
curl -fsSL https://antigravity.google/cli/install.sh | bash
uv run massgen --config massgen/configs/features/fast_iteration_gemini_antigravity.yaml "Create an svg of an AI agent coding."
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.88

Feature highlights:

<!-- Paste feature-highlights.md content here -->
