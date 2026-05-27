# 🚀 Release Highlights — v0.1.91 (2026-05-27)

v0.1.91 hardens MassGen's release-critical configuration paths: YAML parsing is centralized, typo detection is strict enough to block releases, checklist runtime controls now flow through the same orchestrator helper, and native hook permission checks now honor nested protected paths before broad workspace write rules.

### 🧭 Centralized Config Wiring
- `CoordinationConfig.from_dict()` owns `orchestrator.coordination` parsing
- `TimeoutConfig.from_dict()` owns top-level `timeout_settings` parsing
- `AgentConfig.apply_orchestrator_config()` owns top-level orchestrator runtime field application
- CLI helpers remain import-compatible wrappers around the centralized implementations

### 🔎 Config Drift Detection
- Unknown `orchestrator.coordination.*` keys now produce validation warnings
- Unknown top-level `orchestrator.*` and `timeout_settings.*` keys are flagged the same way
- `scripts/validate_all_configs.py --strict` treats those warnings as release-blocking
- Typos such as `fast_interation_mode`, `voting_sensitivty`, and `orchestrator_timout_seconds` now surface before runtime

### ✅ Checklist Runtime Controls
- `max_checklist_calls_per_round` is wired through the centralized orchestrator runtime helper
- `checklist_first_answer` now follows the same runtime path
- Planning controls and subagent timeout fields have parser and documentation parity coverage

### 🛡️ Native Hook Permission Safety
- Gemini CLI and Codex standalone hook scripts now apply more-specific managed paths before broader parents
- Nested read-only/protected paths override workspace-level write access
- Claude Code native hook tests/docs now match the SDK-native `additionalContext` injection contract

### 🧪 Tests
- `massgen/tests/test_config_wiring_refactors.py`
- `massgen/tests/test_coordination_config_wiring.py`
- `massgen/tests/test_config_validator.py`
- `massgen/tests/test_validate_all_configs_script.py`
- `massgen/tests/test_native_hook_adapters.py`
- Updated Gemini CLI and Codex hook script coverage

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Install**:
  ```bash
  pip install massgen==0.1.91
  ```
- **Try It**:
  ```bash
  uv run massgen --config massgen/configs/features/fast_iteration.yaml "Create an svg of an AI agent coding."
  ```
