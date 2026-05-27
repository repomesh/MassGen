# PR Draft: v0.1.91 Config Reliability

## Summary
- Centralize `orchestrator.coordination` YAML parsing in `CoordinationConfig.from_dict()`.
- Centralize top-level `timeout_settings` parsing in `TimeoutConfig.from_dict()`.
- Centralize top-level orchestrator runtime application in `AgentConfig.apply_orchestrator_config()`.
- Keep `cli._parse_coordination_config()` as a compatibility wrapper.
- Keep `cli._parse_timeout_config()` and `cli._apply_orchestrator_runtime_params()` as compatibility wrappers.
- Warn on unknown coordination, orchestrator, and timeout keys so typos such as `fast_interation_mode`, `voting_sensitivty`, and `orchestrator_timout_seconds` surface during validation.
- Make strict config validation release-blocking for unknown config key warnings.
- Wire documented subagent timeout fields and planning controls through the centralized parser.
- Wire validated checklist runtime fields `max_checklist_calls_per_round` and `checklist_first_answer` through the centralized orchestrator runtime helper.
- Harden standalone native hook permission enforcement so nested read-only/protected paths override broader writable parent paths.
- Align Claude Code native hook injection tests/docs with the SDK-native `additionalContext` contract.

## Issues
- Linear: TBD
- GitHub: TBD

## Tests
- `uv run pytest massgen/tests/test_coordination_config_wiring.py massgen/tests/test_config_validator.py massgen/tests/test_validate_all_configs_script.py massgen/tests/test_webui_config_parity.py massgen/tests/test_standalone_checkpoint_config.py -q --tb=short -ra --color=no`
- `uv run pytest massgen/tests/test_config_wiring_refactors.py massgen/tests/test_coordination_config_wiring.py massgen/tests/test_config_validator.py massgen/tests/test_validate_all_configs_script.py massgen/tests/test_webui_config_parity.py massgen/tests/test_standalone_checkpoint_config.py massgen/tests/test_decomposition_bugfixes.py -q --tb=short -ra --color=no`
- `uv run pytest massgen/tests/test_native_hook_adapters.py massgen/tests/test_gemini_cli_hook_script.py massgen/tests/test_codex_hook_script.py massgen/tests/test_gemini_cli_hook_ipc.py massgen/tests/test_codex_hook_ipc.py massgen/tests/test_codex_native_hook_adapter.py -q --tb=short -ra --color=no`
- `uv run pytest massgen/tests/test_api_params_exclusion.py -q --tb=short -ra --color=no`
- `uv run pytest massgen/tests/test_fast_mode.py massgen/tests/test_prompt_improver.py massgen/tests/test_checklist_criteria_presets.py massgen/tests/test_round_evaluator_loop.py massgen/tests/test_novelty_injection.py massgen/tests/test_evolving_criteria.py massgen/tests/test_execution_trace_analyzer.py massgen/tests/test_auto_trace_analysis.py massgen/tests/test_coordination_improvements_config.py massgen/tests/test_config_changedoc.py massgen/tests/test_web_review.py -q --tb=short -ra --color=no`
- `uv run python scripts/validate_all_configs.py --strict`
- `uv run python -m py_compile massgen/agent_config.py massgen/cli.py massgen/config_validator.py massgen/mcp_tools/native_hook_adapters/gemini_cli_hook_script.py massgen/mcp_tools/native_hook_adapters/codex_hook_script.py massgen/tests/test_config_wiring_refactors.py massgen/tests/test_coordination_config_wiring.py massgen/tests/test_validate_all_configs_script.py massgen/tests/test_native_hook_adapters.py massgen/tests/test_gemini_cli_hook_script.py massgen/tests/test_codex_hook_script.py`

## Configs Validated
- `scripts/validate_all_configs.py --strict` validated 281 configs under `massgen/configs`.

## Known Test Lane Note
- Full fast non-API lane currently stops during collection on unrelated in-flight tests:
  - `massgen/tests/frontend/test_launch_run_card.py` imports missing `massgen.frontend.displays.textual_widgets.launch_run_card`
  - `massgen/tests/test_interactive_system_prompt.py` imports missing `InteractiveOrchestratorSection`
