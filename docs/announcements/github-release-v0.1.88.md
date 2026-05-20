# 🚀 Release Highlights — v0.1.88 (2026-05-20)

This is the first version of MassGen's Antigravity integration. v0.1.88 establishes the backend, workspace-local config isolation, MCP config translation, native hook adapter support, and runnable examples. We plan to complete the full integration in the next release.

### 🛰️ Antigravity CLI Backend
- **New backend type** ([#1097](https://github.com/massgen/MassGen/pull/1097)): `antigravity_cli` wraps Google's `agy` binary as a MassGen backend
- **Auth support**: local mode can use existing Google OAuth state at `~/.gemini/google_accounts.json`; `GEMINI_API_KEY` / `GOOGLE_API_KEY` are passed through when present
- **Server-side model selection**: `agy` selects the active model per Antigravity tier; MassGen accepts `model` for logging/registry consistency but does not pass a nonexistent `--model` flag

### 🧰 Workspace-Local Isolation
- Antigravity project state is routed through `<workspace>/.antigravity` via `--gemini_dir`
- MCP config and settings stay inside the MassGen workspace, avoiding mutation of the user's global `~/.gemini/` config
- `.antigravity` / `.antigravitycli` metadata directories are excluded from snapshot meaningful-content heuristics

### 🔌 MCP + Hook Integration
- MassGen MCP server entries are translated to Antigravity's `mcp_config.json` schema
- HTTP MCP servers emit `serverUrl`; stdio servers emit `command` / `args` / `env`
- `AntigravityCLINativeHookAdapter` reuses Gemini CLI hook behavior for Antigravity's compatible hook protocol

### 📦 New Example Configs
- `massgen/configs/providers/antigravity/antigravity_cli_local.yaml` — single Antigravity CLI agent
- `massgen/configs/features/fast_iteration_gemini_antigravity.yaml` — Gemini API + Antigravity CLI fast-iteration pair

### 🧪 Tests
- `massgen/tests/test_antigravity_cli_backend.py` covers binary discovery, command construction, workspace-local config, MCP schema, provider metadata, stdout/error streaming, workflow JSON envelopes, Docker/API-key constraints, native hook adapter wiring, and environment passthrough

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Install**:
  ```bash
  pip install massgen==0.1.88
  curl -fsSL https://antigravity.google/cli/install.sh | bash
  ```
- **Try It**:
  ```bash
  uv run massgen --automation --config massgen/configs/providers/antigravity/antigravity_cli_local.yaml "What is 2+2?"
  ```
