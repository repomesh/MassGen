# MassGen v0.1.84 Roadmap

**Target Release:** May 4, 2026

## Overview

Version 0.1.84 focuses on Dispatch discoverability and git-native multi-agent coordination.

---

## Feature: Dispatch Discoverability Description

**Issue:** [#1034](https://github.com/massgen/MassGen/issues/1034)
**Owner:** @ncrispino

### Goals

- **Discoverability**: Add description to improve Dispatch discoverability so users can quickly understand what Dispatch is and when to use it
- Surface clearer entry points in CLI help, README, and Sphinx docs

### Success Criteria

- [ ] Dispatch description present in CLI `--help`
- [ ] README and Sphinx docs include a clear positioning statement for Dispatch
- [ ] Search/navigation cues (titles, anchors) make Dispatch findable

---

## Feature: GNAP — Git-Native Multi-Agent Coordination

**Issue:** [#1001](https://github.com/massgen/MassGen/issues/1001)
**Owner:** @ncrispino

### Goals

- **Git-native coordination**: A coordination protocol for MassGen's collaborative multi-agent scaling that uses git as the durable substrate (branches/worktrees/commits) for sharing intermediate state, votes, and final answers
- Make agent collaboration auditable and forkable through standard git tooling

### Success Criteria

- [ ] Agents can publish intermediate states/answers as commits on coordination branches
- [ ] Voting and convergence can be reconstructed from git history
- [ ] At least one end-to-end run uses GNAP for coordination

---

## Related Tracks

- **v0.1.83**: In-Session Standalone Checkpoint MCP Integration ([#1079](https://github.com/massgen/MassGen/pull/1079))
- **v0.1.85**: Checkpoint Safety Mode ([#1026](https://github.com/massgen/MassGen/issues/1026)) and Round Evaluator over-indexing fix ([#994](https://github.com/massgen/MassGen/issues/994)) — deferred from v0.1.83

## What's Next

- **v0.1.85**: Checkpoint Safety Mode for Irreversible Actions + Round Evaluator over-indexing fix
