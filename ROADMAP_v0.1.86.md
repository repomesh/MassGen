# MassGen v0.1.86 Roadmap

**Target Release:** May 13, 2026

## Overview

Version 0.1.86 completes the discriminative criteria emergence story started in v0.1.85 and picks up image/video edit capabilities (deferred from v0.1.84/v0.1.85).

---

## Feature: `bootstrap_subagent` LLM Discriminator

**Depends on:** v0.1.85's `bootstrap_criteria` accumulator
**Owner:** @ncrispino

### Goals

- **In-Process Critic**: An LLM pass between rounds that proposes criteria for the accumulator — turning the wired-but-pending `bootstrap_subagent` mode into a fully functional variant
- **Parity with `bootstrap_inline`**: Same end result (criteria augment the next round's checklist), different sourcing (a dedicated critic vs. the answering agents themselves)

### Success Criteria

- [ ] `bootstrap_subagent` runs an LLM critic between rounds
- [ ] Seeded entries flow through the accumulator and are merged into round-N+1's checklist
- [ ] Tests cover the critic pass and propagation end-to-end

---

## Feature: Image/Video Edit Capabilities (Deferred from v0.1.84/v0.1.85)

**Issue:** [#959](https://github.com/massgen/MassGen/issues/959)
**Owner:** @ncrispino

### Goals

- **Edit Capability Coverage**: Investigate and support image and video editing capabilities across providers
- **Multi-Turn Editing**: Multi-turn editing workflows with continuation IDs

### Success Criteria

- [ ] Image editing capabilities documented and tested
- [ ] Video editing capabilities documented and tested
- [ ] Multi-turn editing flow works end-to-end

---

## Related Tracks

- **v0.1.85**: Discriminative Criteria Emergence (`criteria_mode`) — `bootstrap_inline` and `bootstrap_subagent` accumulator infrastructure

## What's Next

- Continued multimodal expansion and provider parity
- Refinements to the discriminative criteria pipeline (selection, ranking, retirement of stale criteria)
