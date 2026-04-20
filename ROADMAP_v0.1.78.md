# MassGen v0.1.78 Roadmap

**Target Release:** April 17, 2026

## Overview

Version 0.1.78 focuses on running MassGen as a cloud job on Modal.

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

- **v0.1.77**: Answer Now Button — faster answers when quality is sufficient ([#1062](https://github.com/massgen/MassGen/pull/1062))
- **v0.1.79**: OpenAI Audio API ([#960](https://github.com/massgen/MassGen/issues/960))
