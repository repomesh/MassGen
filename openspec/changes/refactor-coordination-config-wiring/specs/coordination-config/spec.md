## ADDED Requirements
### Requirement: Centralized Coordination Config Parsing
The system SHALL parse `orchestrator.coordination` through a single centralized parser owned by, or colocated with, `CoordinationConfig`.

#### Scenario: CLI compatibility wrapper
- **WHEN** existing code imports and calls `cli._parse_coordination_config()`
- **THEN** the helper delegates to the centralized parser
- **AND** it returns a `CoordinationConfig` with the same public behavior as before the refactor

#### Scenario: Nested coordination config parsing
- **WHEN** the coordination YAML includes nested sections for persona generation, evaluation criteria generation, prompt improvement, task decomposition, subagent orchestration, or standalone checkpointing
- **THEN** the centralized parser constructs the corresponding typed config objects
- **AND** scalar coordination fields are still applied to the returned `CoordinationConfig`

### Requirement: Coordination Config Key Drift Detection
The system SHALL surface unknown keys under `orchestrator.coordination` during config validation.

#### Scenario: Typo in coordination key
- **WHEN** a config contains `orchestrator.coordination.fast_interation_mode`
- **THEN** validation reports an unknown coordination key warning
- **AND** the warning location identifies `orchestrator.coordination.fast_interation_mode`

#### Scenario: Strict release validation blocks unknown coordination keys
- **WHEN** `scripts/validate_all_configs.py --strict` validates a config containing an unknown coordination key
- **THEN** the command exits non-zero because strict mode treats warnings as release-blocking

### Requirement: Timeout Settings Key Drift Detection
The system SHALL parse top-level `timeout_settings` through `TimeoutConfig` metadata and surface unknown timeout keys during config validation.

#### Scenario: Typo in timeout setting
- **WHEN** a config contains `timeout_settings.orchestrator_timout_seconds`
- **THEN** validation reports an unknown timeout_settings key warning
- **AND** strict config validation exits non-zero because the warning is release-blocking

### Requirement: Centralized Orchestrator Runtime Application
The system SHALL apply top-level `orchestrator` runtime fields through an `AgentConfig`-owned helper.

#### Scenario: CLI compatibility wrapper for orchestrator runtime fields
- **WHEN** existing code calls `cli._apply_orchestrator_runtime_params()`
- **THEN** the helper delegates to `AgentConfig.apply_orchestrator_config()`
- **AND** runtime fields such as `max_checklist_calls_per_round` and `checklist_first_answer` are applied to the returned orchestrator config

#### Scenario: Typo in top-level orchestrator key
- **WHEN** a config contains `orchestrator.voting_sensitivty`
- **THEN** validation reports an unknown orchestrator key warning
- **AND** strict config validation exits non-zero because the warning is release-blocking

### Requirement: Coordination Wiring Parity Tests
The system SHALL include automated tests that detect coordination config wiring drift.

#### Scenario: YAML-addressable field coverage
- **WHEN** a new YAML-addressable `CoordinationConfig` field is added
- **THEN** tests fail until the field is parsed by the centralized parser or explicitly marked non-YAML/internal

#### Scenario: Backend API exclusion coverage
- **WHEN** a coordination field is a MassGen-internal backend parameter
- **THEN** tests fail until it is excluded from backend API parameter forwarding where applicable
