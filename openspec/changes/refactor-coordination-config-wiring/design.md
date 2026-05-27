## Context
Coordination settings affect core orchestration behavior, subagents, checkpointing, round evaluators, criteria modes, memory capture, workspace isolation, and WebUI-driven runs. Adjacent timeout and top-level orchestrator runtime settings affect the same release-critical execution path. New fields currently require edits in multiple places, including config dataclasses, CLI helpers, validators, docs, and tests.

## Goals / Non-Goals
- Goals: centralize parsing, make unknown keys visible, add tests that catch parser drift, and keep v0.1.91 release validation crisp.
- Goals: preserve the existing public `_parse_coordination_config()` helper so current tests and callers do not need a big-bang migration.
- Goals: apply the same pattern to `TimeoutConfig` parsing and top-level orchestrator runtime settings where drift is already visible.
- Non-Goals: change coordination semantics, rename YAML fields, or complete unrelated deferred v0.1.91 features such as image/video editing.

## Decisions
- Decision: add a parser owned by or colocated with `CoordinationConfig`, then make `cli._parse_coordination_config()` delegate to it.
- Decision: maintain an explicit set of non-YAML/internal fields instead of inferring intent from implementation gaps.
- Decision: support explicit nested-to-flat aliases, including `standalone_checkpoint.*` to `standalone_checkpoint_*`, so parity tests do not mistake intentional transforms for missing fields.
- Decision: unknown coordination keys should be warnings in normal validation and release-blocking under strict validation, matching the existing `validate_all_configs.py --strict` behavior.
- Decision: keep nested config parsing explicit for nested objects whose constructors differ from raw YAML shape.
- Decision: make `TimeoutConfig.from_dict()` ignore unknown keys after validation surfaces them, matching the forgiving parse-time behavior used for coordination.
- Decision: make `AgentConfig.apply_orchestrator_config()` own top-level orchestrator runtime field application, with `cli._apply_orchestrator_runtime_params()` retained as a wrapper for WebUI and existing callers.
- Decision: use `AgentConfig.valid_orchestrator_keys()` for top-level orchestrator typo warnings, with a separate non-runtime allowlist for keys handled outside `AgentConfig`.

## Pre-Implementation Audit
- `CoordinationConfig` currently has 81 dataclass fields.
- A direct AST scan of `cli._parse_coordination_config()` found 71 direct `CoordinationConfig(...)` keyword arguments.
- The standalone checkpoint fields are intentionally populated through `**_parse_standalone_checkpoint(...)`, so the new parity tests need an alias/transform map.
- The current parser does not directly wire `plan_depth`, `plan_target_steps`, `plan_target_chunks`, `subagent_min_timeout`, or `subagent_max_timeout`, even though related fields exist in `CoordinationConfig` and some are already validated by `ConfigValidator`.
- `docs/source/reference/yaml_schema.rst` and `docs/source/user_guide/advanced/subagents.rst` already document `subagent_min_timeout` and `subagent_max_timeout` as YAML settings, so tests should treat their parser coverage as a documentation parity bug.
- `plan_depth`, `plan_target_steps`, and `plan_target_chunks` are present in the dataclass and validator but are not currently documented in `docs/source/reference/yaml_schema.rst`; implementation should either wire and document them or explicitly classify them as runtime-only/non-YAML controls.
- The implementation should treat these as red-test candidates and decide under tests whether to preserve legacy behavior or wire them as YAML-addressable fields.
- `timeout_settings` is the runtime path for global timeouts in current configs, but validation did not previously warn on unknown timeout keys.
- `max_checklist_calls_per_round` and `checklist_first_answer` were validated as top-level orchestrator settings but were not applied by `_apply_orchestrator_runtime_params()`, so they are treated as wiring regression candidates.

## Risks / Trade-offs
- Default mismatches between the dataclass and current parser may represent legacy behavior. Mitigation: write regression tests first and document every intentional mismatch in the parser.
- Many active OpenSpec changes touch coordination fields. Mitigation: keep this change focused on wiring infrastructure and avoid changing field names or semantics.
- Strict unknown-key validation may expose existing sample configs with stale keys. Mitigation: run `scripts/validate_all_configs.py --strict` and fix or explicitly allow any intentional legacy keys.

## Migration Plan
1. Add failing parser/validator parity tests.
2. Introduce the centralized parser without removing `_parse_coordination_config()`.
3. Add unknown-key detection in `ConfigValidator`.
4. Update API exclusion parity tests only for fields that are MassGen-internal backend parameters.
5. Run targeted tests, config validation, and the non-API fast lane before release prep.

## Open Questions
- Should unknown coordination keys remain warnings forever, or should a future release promote them to non-strict errors?
- Should intentional parser/dataclass default differences be preserved for backward compatibility or normalized in a later breaking-cleanup change?
