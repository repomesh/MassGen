# MassGen v0.1.90 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.90 — Discriminative Criteria Refinements & Checklist Calibration! 🚀 This release strengthens MassGen's quality loop: criteria that do not distinguish agents are demoted, checklist reasoning is carried into the next round as targeted feedback, candidate answer order is counterbalanced to reduce position bias, and the checklist gate now derives all thresholds from one consistent 0-10 scale.

## Install

```bash
pip install massgen==0.1.90
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.90
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

## Posting Notes

- **Suggested image:** Use a screenshot of the v0.1.90 release notes or a criteria/checklist calibration graphic.

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.90 — Discriminative Criteria Refinements & Checklist Calibration! 🚀 This release strengthens MassGen's quality loop: criteria that do not distinguish agents are demoted, checklist reasoning is carried into the next round as targeted feedback, candidate answer order is counterbalanced to reduce position bias, and the checklist gate now derives all thresholds from one consistent 0-10 scale.

**Key Improvements:**

🎯 **Discriminative-Power Pruning**:
- Bootstrap criteria now compute score spread across agents
- Low-spread, non-discriminative criteria are demoted to `stretch`
- A protected floor keeps enough criteria active so the gate does not collapse

🧠 **Criterion Feedback Loop**:
- Checklist score reasoning is preserved instead of discarded after the verdict
- The lowest-scoring reasoning per criterion becomes the most diagnostic next-round signal
- Agents receive a `<CRITERION FEEDBACK ...>` memo before their next answer

⚖️ **Position-Bias Calibration**:
- Candidate answer order is rotated per scoring agent
- The primacy slot is distributed across agents
- Equal aggregate checklist scores now break deterministically instead of depending on dictionary insertion order

📏 **Unified Checklist Gate**:
- `ChecklistGate.from_budget(...)` derives effective threshold, required-true count, and confidence cutoff together
- All gate values now use the same 0-10 scale
- This prevents scale drift between checklist decision paths

🧩 **Shared Score Utilities**:
- New `massgen/score_utils.py` centralizes score extraction and per-agent score-shape detection
- Checklist, quality, and bootstrap paths now use the same parsing behavior
- Backend circuit-breaker config parsing is consolidated across shared custom-tool/MCP backends

⚡ **Fast-Iteration Config Updates**:
- Fast-iteration examples now default to local command execution
- The default pairings were refreshed for current Gemini, Codex, and Antigravity workflows

🧪 **Tests**:
- New coverage for discriminative pruning, criterion feedback, position-bias calibration, and shared score parsing
- Checklist server tests updated for feedback extraction and gate behavior

**Getting Started:**

```bash
pip install massgen==0.1.90
uv run massgen --config massgen/configs/features/fast_iteration.yaml "Create an svg of an AI agent coding."
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.90

Feature highlights:

<!-- Paste feature-highlights.md content here -->
