# MassGen v0.1.83 Roadmap

**Target Release:** May 1, 2026

## Overview

Version 0.1.83 focuses on checkpoint safety hardening and a round evaluator bug fix.

---

## Feature: Checkpoint Safety Mode for Irreversible Actions

**Issue:** [#1026](https://github.com/massgen/MassGen/issues/1026)
**Owner:** @ncrispino

### Goals

- **Safety Gate**: Dedicated safety mode that gates irreversible actions (deletes, deploys, writes to external systems) behind checkpoint approval before execution
- Complements the existing checkpoint coordination mode with explicit irreversibility detection

### Success Criteria

- [ ] Irreversible action detection working in checkpoint safety mode
- [ ] Checkpoint approval flow blocks execution until reviewer agents sign off

---

## Bug Fix: Round Evaluator Over-indexes on Incremental Fixes

**Issue:** [#994](https://github.com/massgen/MassGen/issues/994)
**Owner:** @ncrispino

### Problem

Managed round evaluator prioritizes incremental fixes despite high spend and strong strategic critique — agents keep polishing surface details instead of making the bold improvements the evaluator flagged.

### Success Criteria

- [ ] Round evaluator correctly weights strategic critique vs. incremental suggestions
- [ ] High-spend rounds trigger more decisive directional changes

---

## Related Tracks

- **v0.1.82**: TUI Copy Mode & Checkpoint Quality Improvements ([#1076](https://github.com/massgen/MassGen/pull/1076))
- **v0.1.84**: Dispatch Discoverability ([#1034](https://github.com/massgen/MassGen/issues/1034)), GNAP git-native coordination ([#1001](https://github.com/massgen/MassGen/issues/1001))

## What's Next

- **v0.1.84**: Dispatch discoverability description + GNAP git-native coordination for multi-agent scaling
