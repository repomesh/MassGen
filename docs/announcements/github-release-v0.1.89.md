# 🚀 Release Highlights — v0.1.89 (2026-05-22)

v0.1.89 completes the follow-up Antigravity CLI integration pass after v0.1.88 introduced the first backend. This release focuses on reliability in real MassGen coordination runs: workflow-tool parity, auth checks, workspace write isolation, native hooks, and prompt affordance gating.

### 🛰️ Workflow-Mode Parity
- Antigravity now mirrors Gemini CLI's `new_answer` / `vote` workflow handling
- `vote` is hidden when no candidate answers exist, keeping agents in `new_answer_only` mode
- Post-evaluation prompts guard against stale `new_answer`, `vote`, or `stop` calls
- Duplicate parsed workflow calls are suppressed within a single turn

### 🧰 Workspace Write Reliability
- `--add-dir <cwd>` registers the MassGen workspace with agy so file tools write where peers and snapshots can see outputs
- Workspace-root `.antigravitycli/` marker prevents agy's upward project discovery from adopting a parent project
- `.antigravity/` and `.antigravitycli/` are ignored as runtime artifacts

### 🔐 Auth + Binary Health Checks
- Backend construction now verifies `agy --version`
- Runs fail fast when no `GEMINI_API_KEY`, `GOOGLE_API_KEY`, or cached Google OAuth credentials are available
- Docker mode still requires API-key auth because OAuth state does not cross container boundaries

### 🔌 Native Hooks
- Antigravity hooks now emit standalone `hooks.json`
- `settings.json` enables hooks through `enableJsonHooks`
- Native hook adapter docs now reflect Antigravity's storage model rather than Gemini CLI's embedded settings hook model

### 🧭 Prompt Guardrails
- `TaskContextSection` advertises `spawn_subagents` only when subagents are enabled
- Multimodal-only agents keep `read_media` context guidance without phantom subagent MCP affordances

### 🧪 Tests
- `massgen/tests/test_antigravity_cli_backend.py` expanded to cover health checks, authentication, workspace anchoring, `--add-dir`, hooks.json, workflow filtering, duplicate tool-call suppression, multimodal prompt flattening, cancellation cleanup, and agent-id propagation
- `massgen/tests/test_system_prompt_sections.py` covers subagent affordance gating

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Install**:
  ```bash
  pip install massgen==0.1.89
  curl -fsSL https://antigravity.google/cli/install.sh | bash
  ```
- **Try It**:
  ```bash
  uv run massgen --config massgen/configs/features/fast_iteration_gemini_antigravity.yaml "Create an svg of an AI agent coding."
  ```
