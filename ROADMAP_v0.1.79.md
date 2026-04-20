# MassGen v0.1.79 Roadmap

**Target Release:** April 20, 2026

## Overview

Version 0.1.79 picks up the Cloud Modal MVP originally planned for v0.1.78 (deferred because v0.1.78 shipped the Circuit Breaker Distributed Store — Phase 4 — instead).

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

- **v0.1.78**: Circuit Breaker Distributed Store — Phase 4 ([#1061](https://github.com/massgen/MassGen/pull/1061)) — pluggable CB state store with in-memory and Redis-backed implementations
- **v0.1.80**: OpenAI Audio API ([#960](https://github.com/massgen/MassGen/issues/960))

## What's Next

- **v0.1.80**: OpenAI Audio API — integrate OpenAI audio API with existing `read_media` tool for audio understanding
- **v0.1.81**: Image/Video Edit Capabilities — investigate and support image/video editing across providers
