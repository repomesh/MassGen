## ADDED Requirements

### Requirement: Compact Consensus Map
The Textual TUI SHALL display a compact Consensus Map during multi-agent runs that summarizes coordination state without replacing the timeline.

#### Scenario: Multi-agent run starts
- **WHEN** the TUI is running with more than one active agent
- **THEN** the Consensus Map is visible below the agent status ribbon
- **AND** it shows one node per agent

#### Scenario: Single-agent or welcome state
- **WHEN** the TUI is on the welcome screen or has only one active agent
- **THEN** the Consensus Map is hidden

### Requirement: Coordination State Rendering
The Consensus Map SHALL show answer, vote, winner, and waiting state from existing TUI coordination events.

#### Scenario: Answers and votes arrive
- **WHEN** agents submit answers and cast votes
- **THEN** the map shows each latest answer label and vote direction
- **AND** the current vote leader is visually distinguished

#### Scenario: Winner selected
- **WHEN** a winner is selected or final presentation starts
- **THEN** the winning agent is marked as winner
- **AND** non-winning agents are shown as complete or waiting

### Requirement: Event Compatibility
The Consensus Map SHALL be driven by existing structured events and direct status callbacks without requiring backend schema changes.

#### Scenario: Unified event pipeline active
- **WHEN** `answer_submitted`, `vote`, `agent_stopped`, `winner_selected`, `final_presentation_start`, `agent_restart`, `phase_change`, or `context_received` events are routed through the TUI
- **THEN** the map state updates from those events

#### Scenario: Direct display fallback active
- **WHEN** direct TUI callbacks update agent status or votes
- **THEN** the map remains accurate for the same visible state
