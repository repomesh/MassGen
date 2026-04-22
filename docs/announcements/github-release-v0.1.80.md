# 🚀 Release Highlights — v0.1.80 (2026-04-22)

### 🎯 [Circuit Breaker Adaptive Thresholds (Phase 5)](https://docs.massgen.ai/en/latest/user_guide/backends.html)
- **Self-tuning thresholds** ([#1065](https://github.com/massgen/MassGen/pull/1065)): Adaptive thresholds respond to each backend's actual failure patterns
- **Effective threshold helpers**: Extracted helper functions for cleaner threshold computation
- **Correctness fixes**: `force_open` metrics gated on actual state transitions; `_open_until` preserved with intent comments

### 🛡️ [New Standalone Checkpoint Modes](https://github.com/massgen/MassGen/blob/main/massgen/mcp_tools/standalone/README.md)
- **Single checkpoint mode** ([#1070](https://github.com/massgen/MassGen/pull/1070)): No recheckpointing within a single operation
- **Draft plan verify mode** ([#1070](https://github.com/massgen/MassGen/pull/1070)): Verify a draft plan before executing

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  pip install massgen==0.1.80
  # Try checkpoint MCP in Claude Code
  claude mcp add massgen-checkpoint-mcp -- \
    uvx --from massgen massgen-checkpoint-mcp --config path/to/config.yaml
  ```
