# MassGen v0.1.81 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.81 — Multi-Region Circuit Breaker Failover (Phase 6)! 🚀 The LLM circuit breaker can now fail over to backup regions when the primary trips OPEN, keeping coordination running through regional outages.

## Install

```bash
pip install massgen==0.1.81
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.81
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.81 — Multi-Region Circuit Breaker Failover (Phase 6)! 🚀 The LLM circuit breaker can now fail over to backup regions when the primary trips OPEN, keeping coordination running through regional outages.

**Key Improvements:**

🌐 **Multi-Region Failover (Phase 6)** — Stay running through regional outages:
- Circuit breaker fails over to backup regions when the primary trips OPEN
- Automatic recovery when the primary region returns to healthy
- Builds on Phase 4 (distributed store) and Phase 5 (adaptive thresholds) for production-grade resilience

**Getting Started:**

```bash
pip install massgen==0.1.81
uv run massgen --config @examples/features/fast_iteration.yaml "Create an svg of an AI agent coding."
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.81

Feature highlights:

<!-- Paste feature-highlights.md content here -->
