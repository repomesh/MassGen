# 🚀 Release Highlights — v0.1.78 (2026-04-17)

### 🔌 Circuit Breaker Distributed Store (Phase 4)

Previously, MassGen's LLM circuit breaker kept its state (failure counts, open/half-open/closed, cooldown timers) *per-process*, so one worker tripping OPEN did not stop its siblings from hammering a rate-limited upstream. v0.1.78 makes that state pluggable and shareable across workers.

- **Pluggable CB state store** ([#1061](https://github.com/massgen/MassGen/pull/1061)): The LLM circuit breaker's state is now held behind a `CircuitBreakerStore` Protocol. Default (`store=None`) preserves the existing single-process behavior.
- **In-memory CB state store**: Thread-safe, zero-dependency implementation for single-process deployments and tests.
- **Redis-backed CB state store**: Distributed implementation via optional `redis>=4.0`; install with `pip install massgen[redis-store]`.
- **Atomic CB transitions**: `atomic_record_failure` / `atomic_record_success` make CB state transitions linearizable when multiple workers race on the same upstream backend.
- **Phase 3 CB metrics hooks** fire on every store code path — observability you configured in v0.1.76 continues to work unchanged.

---

### 📖 Getting Started

- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation): Try the new features today.
- **Try It**:

```bash
# Base install (unchanged default behavior)
pip install massgen==0.1.78

# With the distributed (Redis-backed) circuit breaker store
pip install "massgen[redis-store]==0.1.78"
```

## What's Changed

* feat: add distributed store backend for circuit breaker (Phase 4) by @amabito in https://github.com/massgen/MassGen/pull/1061

**Full Changelog**: https://github.com/massgen/MassGen/compare/v0.1.77...v0.1.78
