# MassGen v0.1.80 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.80 — Adaptive Circuit Breaker & Checkpoint Modes! 🚀 Circuit breaker Phase 5 adds adaptive thresholds that tune themselves to each backend's behavior. New standalone checkpoint modes: single checkpoint (no recheckpointing) and draft plan verify mode.

## Install

```bash
pip install massgen==0.1.80
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.80
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.80 — Adaptive Circuit Breaker & Checkpoint Modes! 🚀 Circuit breaker Phase 5 adds adaptive thresholds that tune themselves to each backend's behavior. New standalone checkpoint modes for tighter safety loops.

**Key Improvements:**

🎯 **Circuit Breaker Adaptive Thresholds (Phase 5)** — Self-tuning rate-limit protection:
- Adaptive thresholds respond to each backend's actual failure patterns
- Effective threshold computation helpers for cleaner logic
- `force_open` metrics gated on actual state transitions
- Preserves `_open_until` with intent comments for clearer semantics

🛡️ **New Standalone Checkpoint Modes** — Tighter safety loops:
- **Single checkpoint mode** — No recheckpointing within a single operation
- **Draft plan verify mode** — Verify a draft plan before executing

**Getting Started:**

```bash
pip install massgen==0.1.80
# Try checkpoint MCP in Claude Code
claude mcp add massgen-checkpoint-mcp -- \
  uvx --from massgen massgen-checkpoint-mcp --config path/to/config.yaml
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.80

Feature highlights:

<!-- Paste feature-highlights.md content here -->
