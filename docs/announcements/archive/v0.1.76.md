# MassGen v0.1.76 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.76 — Exa Search & Circuit Breaker Observability! 🚀 New Exa AI-powered search tool for MCP. Circuit breaker Phase 3 adds observability with probe ownership, lock release, and per-attempt latency tracking. Copyable checkpoint agent instructions and Docker dependency fixes.

## Install

```bash
pip install massgen==0.1.76
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.76
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.76 — Exa Search & Circuit Breaker Observability! 🚀 New Exa AI-powered search tool for MCP. Circuit breaker Phase 3 adds observability with probe ownership, lock release, and per-attempt latency tracking. Copyable checkpoint agent instructions and Docker dependency fixes.

**Key Improvements:**

🔍 **Exa AI Search Tool** — AI-powered search via MCP:
- New Exa search tool added to MCP server registry
- Example config: `exa_search_example.yaml`

📊 **Circuit Breaker Observability (Phase 3)** — Full visibility into rate limit protection:
- Probe ownership and lock release mechanisms
- Per-attempt latency regression tracking
- Strengthened observability across all backends

**Plus:**
- 📋 **Checkpoint agent instructions** — Copyable custom instructions for agent memory files with checkpoint MCP information
- 🐳 **Docker dependency fixes** — Fixed Dockerfile installs for reliable container builds

**Getting Started:**

```bash
pip install massgen==0.1.76
uv run massgen --config @examples/tools/web-search/exa_search_example "Research the latest breakthroughs in multi-agent AI systems"
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.76

Feature highlights:

<!-- Paste feature-highlights.md content here -->
