# 🚀 Release Highlights — v0.1.79 (2026-04-20)

### ⚡ [Better Fast Mode Options](https://github.com/massgen/MassGen/blob/main/massgen/configs/features/fast_iteration.yaml)
- **Fine-grained speed control**: New options to control how fast the coordination runs — dial in the right speed vs. quality tradeoff for your use case

### 🛡️ [Broader Checkpoint Framing](https://github.com/massgen/MassGen/blob/main/docs/modules/checkpoint.md)
- **Beyond safety-only**: Checkpoint mode now covers both high-stakes actions AND coordinated phases — use for deploys, deletions, financial ops, AND for coordinated planning steps

### 📋 Checkpoint Updates
- **Checkpoint instructions clarity**: More clarity in trust settings for checkpoint agents

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  pip install massgen==0.1.79
  uv run massgen --config @examples/features/fast_iteration.yaml "Create an svg of an AI agent coding."
  ```
