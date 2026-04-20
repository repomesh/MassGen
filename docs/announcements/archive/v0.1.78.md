# MassGen v0.1.78 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.78 — Circuit Breaker Distributed Store (Phase 4)! 🚀 The LLM circuit breaker's state (failure counts, open/half-open/closed, cooldown timers) is now pluggable and can be shared across workers and processes, with in-memory and Redis-backed implementations.

## Install

```bash
# Base install (unchanged default behavior)
pip install massgen==0.1.78

# With distributed (Redis-backed) circuit breaker store
pip install "massgen[redis-store]==0.1.78"
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.78
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.78 — Circuit Breaker Distributed Store (Phase 4)! 🚀

Previously, MassGen's LLM circuit breaker kept its state per-process, so one worker tripping OPEN didn't stop its siblings from hammering a rate-limited upstream. v0.1.78 makes that state pluggable and shareable across workers.

**Key Improvements:**

🔌 **Pluggable CB state store** — LLM circuit breaker state (failure counts, open/half-open/closed, cooldown timers) now lives behind a `CircuitBreakerStore` Protocol. Default behavior is unchanged (single-process).

🧠 **In-memory CB store** — Thread-safe, zero-dependency implementation for single-process deployments and tests.

🗃️ **Redis-backed CB store** — Distributed implementation (optional `redis>=4.0`) so all processes share CB state; install with `pip install massgen[redis-store]`.

⚛️ **Atomic CB transitions** — `atomic_record_failure` / `atomic_record_success` make state transitions linearizable when workers race on the same upstream backend.

**Getting Started:**

```bash
pip install massgen==0.1.78

# Or, with the distributed Redis-backed circuit breaker store:
pip install "massgen[redis-store]==0.1.78"
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.78

Feature highlights:

<!-- Paste feature-highlights.md content here -->
