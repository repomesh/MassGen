# MassGen v0.1.79 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.79 — Fast Mode Speed Control & Broader Checkpoint Framing! 🚀 New fast mode options give fine-grained control over speed vs. quality tradeoffs. Checkpoint framing broadened from safety-only to high-stakes and coordinated phases. Multimodal default change and checkpoint instructions clarity improvements.

## Install

```bash
pip install massgen==0.1.79
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.79
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.79 — Fast Mode Speed Control & Broader Checkpoint Framing! 🚀 New fast mode options give fine-grained control over speed vs. quality tradeoffs. Checkpoint framing broadened from safety-only to high-stakes and coordinated phases.

**Key Improvements:**

⚡ **Better Fast Mode Options** — Fine-grained speed control:
- New options to control how fast the coordination runs
- Dial in the right speed vs. quality tradeoff for your use case

🛡️ **Broader Checkpoint Framing** — Beyond safety-only:
- Checkpoint mode now covers both high-stakes actions AND coordinated phases
- Use checkpoint for deploys, deletions, financial ops — AND for coordinated planning steps

**Plus:**
- 🖼️ **Multimodal default change** — Updated default behavior and YAML fix
- 📋 **Checkpoint instructions clarity** — More clarity in trust settings for checkpoint agents

**Getting Started:**

```bash
pip install massgen==0.1.79
uv run massgen --config @examples/features/fast_iteration.yaml "Create an svg of an AI agent coding."
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.79

Feature highlights:

<!-- Paste feature-highlights.md content here -->
