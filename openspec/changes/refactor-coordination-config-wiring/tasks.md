## 1. Acceptance Tests
- [x] 1.1 Add `massgen/tests/test_config_validator.py::TestConfigValidator::test_unknown_coordination_key_warns` showing `fast_interation_mode` produces a warning at `orchestrator.coordination.fast_interation_mode`
- [x] 1.2 Add a strict script test, likely in `massgen/tests/test_validate_all_configs_script.py`, showing `scripts/validate_all_configs.py --strict --directory <tmpdir>` exits non-zero for a config with an unknown coordination key
- [x] 1.3 Add `massgen/tests/test_coordination_config_wiring.py::test_yaml_addressable_coordination_fields_have_parser_coverage` to fail when a dataclass field is neither parsed nor explicitly documented as nested/internal
- [x] 1.4 Add `massgen/tests/test_coordination_config_wiring.py::test_cli_parse_coordination_config_delegates_to_central_parser` proving `cli._parse_coordination_config()` uses the centralized parser
- [x] 1.5 Add `massgen/tests/test_coordination_config_wiring.py::test_nested_coordination_sections_still_parse` covering persona generator, evaluation criteria generator, prompt improver, task decomposer, subagent orchestrator, and standalone checkpoint fields
- [x] 1.6 Add scalar regression tests for currently drift-prone fields: `plan_depth`, `plan_target_steps`, `plan_target_chunks`, `subagent_min_timeout`, and `subagent_max_timeout`
- [x] 1.7 Add a documentation parity assertion or fixture proving documented YAML fields such as `subagent_min_timeout` and `subagent_max_timeout` are parser-covered
- [x] 1.8 Add `massgen/tests/test_config_wiring_refactors.py` coverage for `TimeoutConfig` parser metadata and CLI timeout parser delegation
- [x] 1.9 Add `massgen/tests/test_config_wiring_refactors.py` coverage for `AgentConfig` owning top-level orchestrator runtime application and for wiring `max_checklist_calls_per_round` / `checklist_first_answer`
- [x] 1.10 Extend validator and strict-script tests so unknown `orchestrator.*` and `timeout_settings.*` keys fail strict validation

## 2. Implementation
- [x] 2.1 Add the centralized coordination config parser in or near `massgen/agent_config.py`
- [x] 2.2 Replace the body of `cli._parse_coordination_config()` with a compatibility wrapper
- [x] 2.3 Add an explicit allowlist or metadata set for YAML-addressable coordination keys
- [x] 2.4 Teach `ConfigValidator` to warn on unknown coordination keys
- [x] 2.5 Update API parameter exclusion parity coverage for any newly classified internal backend parameters
- [x] 2.6 Add `TimeoutConfig.from_dict()` and timeout key metadata, then route CLI timeout parsing through it
- [x] 2.7 Add `AgentConfig.apply_orchestrator_config()` and top-level orchestrator key metadata, then route the CLI runtime helper through it
- [x] 2.8 Teach `ConfigValidator` to warn on unknown top-level `orchestrator` and `timeout_settings` keys

## 3. Verification
- [x] 3.1 Run targeted parser and validator tests with pytest log capture: `uv run pytest massgen/tests/test_coordination_config_wiring.py massgen/tests/test_config_validator.py massgen/tests/test_validate_all_configs_script.py -q --tb=short -ra --color=no`
- [x] 3.2 Run `uv run python scripts/validate_all_configs.py --strict`
- [x] 3.3 Run the fast non-API test lane or an agreed focused subset if unrelated active work blocks the full lane
  - Full lane attempted; collection is blocked by unrelated in-flight tests for missing launch-run/interactive prompt modules. Focused coordination parser, validator, API exclusion, and release config gates pass.
- [x] 3.4 Run `uv run py_compile` or equivalent import/compile check for touched Python modules if the focused pytest subset does not import every changed path
- [x] 3.5 Update `PR_DRAFT.md` or create it after confirming whether this release PR should append or start fresh
- [x] 3.6 Prepare v0.1.91 release notes once implementation is green
- [x] 3.7 Run the expanded parser/validator/WebUI parity slice including `massgen/tests/test_config_wiring_refactors.py`

## 4. Release Readiness
- [x] 4.1 Update `CHANGELOG.md` under `[Unreleased]` with the coordination config reliability feature, refactor summary, and test list
- [x] 4.2 Update `README.md` v0.1.91 Roadmap; defer Recent Achievements wording until the release branch is finalized
- [x] 4.3 Update `docs/source/reference/yaml_schema.rst` if parser changes make previously undocumented YAML fields (`plan_depth`, `plan_target_steps`, `plan_target_chunks`) official, or if unknown-key warnings need user-facing documentation
- [x] 4.4 Confirm `docs/source/user_guide/advanced/subagents.rst` remains accurate for `subagent_min_timeout` and `subagent_max_timeout` after parser wiring is fixed
- [ ] 4.5 Run `release-prep v0.1.91` after the release PR is merged or when the maintainer is ready to generate announcements
- [ ] 4.6 Confirm whether Image/Video Edit Capabilities (#959), currently noted as deferred to v0.1.91, stays separate or is added to this release train before finalizing release notes

## What's Next
- After approval, start with the failing acceptance tests above, then implement the minimum parser and validator changes needed to turn them green.
- After this lands, decide whether v0.1.91 should also include the deferred image/video editing feature from `CHANGELOG.md` or keep that as a separate release train.
