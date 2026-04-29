# MassGen v0.1.82 Roadmap

**Target Release:** April 29, 2026

## Overview

Version 0.1.82 picks up the Cloud Modal MVP originally planned for v0.1.81 (deferred again because v0.1.81 shipped Multi-Region Circuit Breaker Failover (Phase 6) instead).

---

## Feature: Cloud Modal MVP

**Issue:** [#982](https://github.com/massgen/MassGen/issues/982)
**Owner:** @ncrispino

### Goals

- **Cloud Execution**: Run MassGen jobs in the cloud via `--cloud` option on Modal
- Progress streams to terminal, results saved locally under `.massgen/cloud_jobs/`

### Success Criteria

- [ ] Cloud job execution functional on Modal
- [ ] Progress streaming and artifact extraction working

---

## Related Tracks

- **v0.1.81**: Multi-Region Circuit Breaker Failover (Phase 6) — regional failover, automatic recovery ([#1072](https://github.com/massgen/MassGen/pull/1072))
- **v0.1.83**: OpenAI Audio API ([#960](https://github.com/massgen/MassGen/issues/960))

## What's Next

- **v0.1.83**: OpenAI Audio API — integrate OpenAI audio API with existing `read_media` tool for audio understanding
- **v0.1.84**: Image/Video Edit Capabilities — investigate and support image/video editing across providers
