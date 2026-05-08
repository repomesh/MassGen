## 1. Tests
- [x] 1.1 Add unit tests for Consensus Map state transitions.
- [x] 1.2 Add Textual widget tests for compact rendering and visibility.
- [x] 1.3 Add runtime TUI snapshot coverage for answer, vote, and winner state.

## 2. Implementation
- [x] 2.1 Add `ConsensusMapState` and `ConsensusMap` widget.
- [x] 2.2 Export the widget from `textual_widgets`.
- [x] 2.3 Mount the strip below the agent status ribbon and hide it for welcome/single-agent states.
- [x] 2.4 Wire structured coordination events and direct status callbacks into the map.
- [x] 2.5 Add theme styling using existing TUI variables and agent color classes.

## 3. Validation
- [x] 3.1 Run targeted frontend tests.
- [x] 3.2 Run `openspec validate add-tui-consensus-map --strict`.

## What's Next
- Consider merging the map’s state summary with `add-tui-workflow-comprehension` so the visual map and conversational narrator share one source of truth.
