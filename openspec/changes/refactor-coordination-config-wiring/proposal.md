# Change: Refactor release-critical config wiring for v0.1.91

## Why
Release-critical config surfaces have grown across `orchestrator.coordination`, `timeout_settings`, and top-level `orchestrator` runtime keys. Several of these paths were still manually wired through `cli.py`, and a missed field or typo could silently change runtime behavior, so v0.1.91 should harden these paths with focused refactors and validation features.

## What Changes
- Move coordination config parsing to a single parser owned by, or colocated with, `CoordinationConfig`
- Keep `cli.py` as a compatibility wrapper around the centralized parser
- Move timeout settings parsing to `TimeoutConfig.from_dict()` and keep CLI parsing as a compatibility wrapper
- Move top-level orchestrator runtime application to `AgentConfig.apply_orchestrator_config()` and keep the CLI helper as a compatibility wrapper
- Add validation warnings for unknown `orchestrator.coordination.*` keys so typos are visible and `scripts/validate_all_configs.py --strict` fails
- Add validation warnings for unknown `timeout_settings.*` and top-level `orchestrator.*` keys using the same strict-release behavior
- Add parity tests that prove YAML-addressable coordination fields are parsed, validated, and not leaked to backend API params where applicable
- Preserve existing runtime behavior unless a default mismatch is explicitly documented and covered by tests

## Impact
- Affected specs: `coordination-config`
- Affected code: `massgen/agent_config.py`, `massgen/cli.py`, `massgen/config_validator.py`, `massgen/backend/base.py`, `massgen/api_params_handler/_api_params_handler_base.py`, `massgen/tests/`
- Release target: v0.1.91 reliability/refactor work; compatible with larger deferred feature work noted in `CHANGELOG.md`

## Acceptance Tests
- A typo such as `fast_interation_mode` under `orchestrator.coordination` produces a validation warning, and strict validation treats it as release-blocking
- Every YAML-addressable `CoordinationConfig` field is either parsed by the centralized parser or explicitly marked as non-YAML/internal
- `_parse_coordination_config()` remains import-compatible and delegates to the centralized parser
- Existing nested coordination config parsing still works for persona generation, evaluation criteria generation, prompt improvement, task decomposition, subagent orchestrator, and standalone checkpoint fields
- Targeted config/parity tests and `scripts/validate_all_configs.py --strict` pass before release prep
- Release notes and user-facing YAML reference docs are updated if implementation changes documented config behavior
- Timeout and orchestrator runtime parser helpers have metadata coverage, CLI delegation tests, and strict validation coverage for typo keys
