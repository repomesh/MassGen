# MassGen v0.1.90 Roadmap

**Target Release:** May 25, 2026

## Overview

Version 0.1.90 picks up the image/video edit work deferred from v0.1.86-v0.1.89 and continues refinement of the discriminative criteria pipeline.

---

## Feature: Image/Video Edit Capabilities (Deferred from v0.1.86-v0.1.89)

**Issue:** [#959](https://github.com/massgen/MassGen/issues/959)
**Owner:** @ncrispino

### Goals

- **Edit Capability Coverage**: Investigate and support image and video editing capabilities across providers
- **Multi-Turn Editing**: Multi-turn editing workflows with continuation IDs
- **Provider Parity**: Document which providers support generation, editing, continuation, and media input/output combinations

### Success Criteria

- [ ] Image editing capabilities documented and tested
- [ ] Video editing capabilities documented and tested
- [ ] Multi-turn editing flow works end-to-end
- [ ] Provider capability notes are updated where users discover multimodal examples

---

## Feature: Discriminative Criteria Refinements

**Depends on:** v0.1.85 `bootstrap_inline` and v0.1.86 `bootstrap_subagent`
**Owner:** @ncrispino

### Goals

- **Selection and Ranking**: Keep the most useful emergent criteria prominent as the accumulator grows
- **Stale Criteria Retirement**: Avoid long-running refinement loops carrying obsolete criteria indefinitely
- **Operational Clarity**: Improve docs and examples for choosing `bootstrap_inline` vs. `bootstrap_subagent`

### Success Criteria

- [ ] Criteria refinement behavior is documented
- [ ] Tests cover ranking/selection or stale-criteria retirement behavior if implemented
- [ ] Examples clearly distinguish agent-proposed and critic-proposed criteria flows

---

## Related Tracks

- **v0.1.89**: Antigravity CLI full integration and hardening — workflow-mode parity, auth checks, workspace project anchoring, standalone hooks.json, and prompt affordance gating
- **v0.1.88**: Antigravity CLI backend wrapping Google's `agy` binary, with workspace-local `.antigravity/` config isolation and runnable Antigravity examples
- **v0.1.87**: Documentation — framework comparison pages (CrewAI, LangGraph, AutoGen) and `llms.txt` index ([#1094](https://github.com/massgen/MassGen/pull/1094)); plus a one-line `refine=False` fix for the `bootstrap_subagent` discriminator
- **v0.1.86**: Functional `bootstrap_subagent` discriminator and Codex MCP approval fix
- **v0.1.85**: Discriminative Criteria Emergence (`criteria_mode`) — `bootstrap_inline` and accumulator infrastructure

## What's Next

- Continued multimodal expansion and provider parity
- Further quality-loop ergonomics for long-running multi-agent refinement
