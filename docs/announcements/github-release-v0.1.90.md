# 🚀 Release Highlights — v0.1.90 (2026-05-25)

v0.1.90 strengthens MassGen's checklist-gated refinement loop: non-discriminative criteria are softened, checklist reasoning becomes next-round feedback, candidate ordering is counterbalanced, and gate thresholds now share one consistent 0-10 scale.

### 🎯 Discriminative-Power Pruning
- Bootstrap criteria now compute per-criterion score spread across agents
- Low-spread criteria are demoted to `stretch` so they stay visible without acting as hard gates
- A protected floor prevents the gate from being hollowed out

### 🧠 Criterion Feedback Loop
- Checklist score reasoning is extracted after each verdict
- Per-agent score submissions keep the lowest-score reasoning per criterion as the most diagnostic signal
- Next-round agents receive a `<CRITERION FEEDBACK ...>` memo with failed criteria marked

### ⚖️ Position-Bias Calibration
- Candidate answer order rotates per scoring agent
- Primacy-slot exposure is distributed across agents
- Equal aggregate checklist scores break deterministically, independent of insertion order

### 📏 Unified Checklist Gate
- `ChecklistGate.from_budget(...)` derives effective threshold, required-true count, and confidence cutoff together
- The checklist gate now consistently uses a 0-10 threshold scale
- Fast-iteration defaults continue to relax the gate as answer budget tightens

### 🧩 Shared Score Utilities
- New `massgen/score_utils.py` centralizes score extraction and per-agent score-shape detection
- Checklist server, quality server, and bootstrap criteria now share the same parsing behavior
- `llm_circuit_breaker_*` kwarg parsing is consolidated into the shared custom-tool/MCP backend base

### ⚡ Fast-Iteration Config Updates
- Fast-iteration examples now default to local command execution
- `fast_iteration.yaml` refreshes its default pairings for current Gemini + Codex workflows
- Antigravity fast-iteration config remains available for CLI-backed Google runs

### 🧪 Tests
- `massgen/tests/test_discriminative_pruning.py`
- `massgen/tests/test_criterion_feedback.py`
- `massgen/tests/test_position_bias_calibration.py`
- `massgen/tests/test_score_utils.py`
- Updated `massgen/tests/test_checklist_tools_server.py`

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Install**:
  ```bash
  pip install massgen==0.1.90
  ```
- **Try It**:
  ```bash
  uv run massgen --config massgen/configs/features/fast_iteration.yaml "Create an svg of an AI agent coding."
  ```
