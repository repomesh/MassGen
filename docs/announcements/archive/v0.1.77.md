# MassGen v0.1.77 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.77 — Answer Now Button! 🚀 New "Answer Now" button lets agents submit answers more quickly, both within a round, and bypassing additional refinement rounds when the answer is already good enough.

## Install

```bash
pip install massgen==0.1.77
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.77
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.77 — Answer Now Button! 🚀 New "Answer Now" button lets agents submit answers more quickly, both within a round, and bypassing additional refinement rounds when the answer is already good enough.

**Key Improvements:**

⚡ **Answer Now Button** — Faster answers when quality is already sufficient:
- Agents can submit answers immediately without waiting for additional refinement rounds
- Reduces time-to-answer for tasks where early rounds already produce good results

**Plus:**
- 📋 **Updated checkpoint instructions** — Refined agent memory instructions for checkpoint MCP
- 📝 **Updated coordination workflow docs** — Clarified coordination workflow documentation

**Getting Started:**

```bash
pip install massgen==0.1.77
uv run massgen --config @examples/features/fast_iteration.yaml "Create an svg of an AI agent coding."
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.77

Feature highlights:

<!-- Paste feature-highlights.md content here -->
