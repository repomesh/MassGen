# Change: Add TUI Consensus Map

## Why
Multi-agent runs expose rich coordination state, but users must currently infer convergence by reading timelines, toasts, status text, and vote cards. A compact visual map would make the physical shape of collaboration visible without hiding agent output.

## What Changes
- Add a compact Consensus Map strip below the Textual TUI status ribbon during multi-agent runs.
- Show agent nodes, latest answer labels, vote arrows, current leader/winner, and waiting/working states.
- Feed the map from existing structured coordination events and status callbacks.
- Hide the map on welcome and single-agent runs.

## Impact
- Affected specs: textual-tui
- Affected code:
  - `massgen/frontend/displays/textual_widgets/` for the new state/widget
  - `massgen/frontend/displays/textual_terminal_display.py` for mounting and event/status wiring
  - `massgen/frontend/displays/textual_themes/base.tcss` for styling
  - `massgen/tests/frontend/` for state, widget, and runtime snapshot coverage
