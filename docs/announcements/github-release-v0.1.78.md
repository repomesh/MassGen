# 🚀 Release Highlights — v0.1.78 (2026-04-17)

### 🔌 Circuit Breaker Distributed Store (Phase 4)
- **Pluggable CB state store** ([#1061](https://github.com/massgen/MassGen/pull/1061)): The LLM circuit breaker's state is now held behind a `CircuitBreakerStore` Protocol and can be shared across workers and processes. Default (`store=None`) preserves the existing single-process behavior.
- **In-memory CB state store**: Thread-safe, zero-dependency implementation for single-process deployments and tests.
- **Redis-backed CB state store**: Distributed implementation via optional `redis>=4.0`; install with `pip install massgen[redis-store]`.
- **Atomic CB transitions**: `atomic_record_failure` / `atomic_record_success` on the Protocol make CB state transitions linearizable when workers race on the same upstream backend.

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  # Base install (unchanged default behavior)
  pip install massgen==0.1.78

  # With distributed (Redis-backed) circuit breaker store
  pip install "massgen[redis-store]==0.1.78"
  ```
