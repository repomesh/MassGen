# 🚀 Release Highlights — v0.1.81 (2026-04-27)

### 🌐 [Multi-Region Circuit Breaker Failover (Phase 6)](https://docs.massgen.ai/en/latest/user_guide/backends.html)
- **Regional failover** ([#1072](https://github.com/massgen/MassGen/pull/1072)): LLM circuit breaker fails over to backup regions when the primary trips OPEN
- **Automatic recovery**: Returns to the primary region when it becomes healthy again
- **Production-grade resilience**: Builds on Phase 4 (distributed store) and Phase 5 (adaptive thresholds) for full multi-region resilience

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  pip install massgen==0.1.81
  uv run massgen --config @examples/features/fast_iteration.yaml "Create an svg of an AI agent coding."
  ```
