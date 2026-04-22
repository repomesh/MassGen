#!/usr/bin/env python3
"""Standalone validator for checkpoint plan JSON files.

Self-contained — no massgen imports. Designed to run inside Docker
containers where agents validate their checkpoint_result.json before
submitting.

Mirrors the server-side validator at
`checkpoint_mcp_server.validate_plan_output` and
`checkpoint_mcp_server.validate_recovery_node`. The two are kept in
sync via a parity test (test_validator_parity.py); do NOT let them
drift.

Usage:
    python validate_plan.py <path_to_json_file>

Exit codes:
    0 = PASS
    1 = FAIL (with error details on stderr)
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

VALID_TERMINALS: set[str] = {"proceed", "recheckpoint", "terminate"}
VALID_STEP_KINDS: set[str] = {"verify", "action", "backup", "notify", "wait"}

# Preconditions reference a prior step's `proceed` terminal; `terminate`
# halts the plan so cannot be a precondition for anything downstream.
_PRECONDITION_RE = re.compile(r"^step:(\d+)\.proceed$")


def _validate_action_spec(spec: Any, path: str) -> list[str]:
    """Validate that `spec` is a dict with `tool` and `args`."""
    errors: list[str] = []
    if not isinstance(spec, dict):
        errors.append(f"{path}: must be a dict with 'tool' and 'args'")
        return errors
    if "tool" not in spec:
        errors.append(f"{path}: missing 'tool'")
    elif not isinstance(spec["tool"], str) or not spec["tool"].strip():
        errors.append(f"{path}.tool: must be a non-empty string")
    if "args" not in spec:
        errors.append(f"{path}: missing 'args'")
    elif not isinstance(spec["args"], dict):
        errors.append(f"{path}.args: must be a dict")
    return errors


def validate_recovery_node(node: Any, path: str = "recovery") -> list[str]:
    """Validate a recovery node recursively. Returns list of errors.

    Three node types:
    - `str`: terminal. One of `proceed`/`recheckpoint`/`terminate`.
    - `dict` with `if`: branch node with `if`/`then`/optional `else`/optional `reason`.
    - `dict` with `compensate`: compensate node with action spec + `then`/optional `reason`.
    """
    errors: list[str] = []

    if isinstance(node, str):
        if node not in VALID_TERMINALS:
            errors.append(
                f"{path}: invalid terminal value '{node}', " f"must be one of {sorted(VALID_TERMINALS)}",
            )
        return errors

    if not isinstance(node, dict):
        errors.append(
            f"{path}: must be a string terminal or a dict (branch or compensate node)",
        )
        return errors

    # Compensate node
    if "compensate" in node:
        errors.extend(_validate_action_spec(node["compensate"], f"{path}.compensate"))
        if "then" not in node:
            errors.append(f"{path}: compensate node missing 'then'")
        else:
            errors.extend(validate_recovery_node(node["then"], f"{path}.then"))
        if "reason" in node and not isinstance(node["reason"], str):
            errors.append(f"{path}.reason: must be a string when present")
        return errors

    # Branch node
    if "if" not in node:
        errors.append(
            f"{path}: missing 'if' field (branch node) or 'compensate' field (compensate node)",
        )
        return errors
    if "then" not in node:
        errors.append(f"{path}: missing 'then' field")
        return errors
    if not isinstance(node["if"], str):
        errors.append(f"{path}.if: must be a string")
    errors.extend(validate_recovery_node(node["then"], f"{path}.then"))
    if "else" in node:
        errors.extend(validate_recovery_node(node["else"], f"{path}.else"))
    if "reason" in node and not isinstance(node["reason"], str):
        errors.append(f"{path}.reason: must be a string when present")
    return errors


def _validate_preconditions(
    preconditions: Any,
    current_step_num: int,
    known_steps: set[int],
    path: str,
) -> list[str]:
    """Validate `preconditions` list on a step."""
    errors: list[str] = []
    if not isinstance(preconditions, list):
        errors.append(f"{path}: must be a list of 'step:N.proceed' strings")
        return errors
    for j, ref in enumerate(preconditions):
        ref_path = f"{path}[{j}]"
        if not isinstance(ref, str):
            errors.append(f"{ref_path}: must be a string, got {type(ref).__name__}")
            continue
        match = _PRECONDITION_RE.match(ref)
        if not match:
            errors.append(
                f"{ref_path}: '{ref}' does not match the required format 'step:N.proceed'",
            )
            continue
        referenced = int(match.group(1))
        if referenced >= current_step_num:
            errors.append(
                f"{ref_path}: references step {referenced} which is not " f"strictly earlier than the current step ({current_step_num}); " "forward and self-references are not allowed",
            )
        elif referenced not in known_steps:
            errors.append(
                f"{ref_path}: references step {referenced} which does not exist in the plan",
            )
    return errors


def validate_plan(raw: dict[str, Any]) -> list[str]:
    """Validate a checkpoint plan dict. Returns list of errors.

    Required top-level: `plan` (non-empty list of steps).

    Required per step: `step` (int), `description` (str), `kind`
    (enum), `preconditions` (list, may be empty), `touches` (list, may
    be empty), `recovery` (RecoveryNode).

    Optional per step: `constraints` (list[str]), `approved_action`
    (dict with `goal_id`/`tool`/`args`).

    Rollback rule: on `kind:action` steps, `approved_action.rollback`
    is required (action spec dict OR explicit None). On other kinds,
    `rollback` is forbidden.
    """
    errors: list[str] = []

    if "plan" not in raw:
        errors.append("Output missing required 'plan' field")
        return errors

    plan = raw["plan"]
    if not isinstance(plan, list):
        errors.append("'plan' must be a list of steps")
        return errors
    if len(plan) == 0:
        errors.append("'plan' must not be empty")
        return errors

    # First pass: collect known step numbers for precondition validation.
    known_steps: set[int] = set()
    for step in plan:
        if isinstance(step, dict) and isinstance(step.get("step"), int):
            known_steps.add(step["step"])

    for i, step in enumerate(plan):
        prefix = f"plan[{i}]"
        if not isinstance(step, dict):
            errors.append(f"{prefix}: must be a dict")
            continue

        # Required: step (int)
        if "step" not in step:
            errors.append(f"{prefix}: missing required 'step' field")
            step_num = -1  # sentinel
        elif not isinstance(step["step"], int):
            errors.append(
                f"{prefix}.step: must be an int, got {type(step['step']).__name__}",
            )
            step_num = -1
        else:
            step_num = step["step"]

        # Required: description
        if "description" not in step:
            errors.append(f"{prefix}: missing required 'description' field")
        elif not isinstance(step["description"], str):
            errors.append(f"{prefix}.description: must be a string")

        # Required: kind
        if "kind" not in step:
            errors.append(
                f"{prefix}: missing required 'kind' field " f"(one of {sorted(VALID_STEP_KINDS)})",
            )
            kind = None
        else:
            kind = step["kind"]
            if kind not in VALID_STEP_KINDS:
                errors.append(
                    f"{prefix}.kind: '{kind}' not in {sorted(VALID_STEP_KINDS)}",
                )

        # Required: preconditions
        if "preconditions" not in step:
            errors.append(
                f"{prefix}: missing required 'preconditions' field " "(use empty list [] if no preconditions)",
            )
        elif step_num != -1:
            errors.extend(
                _validate_preconditions(
                    step["preconditions"],
                    step_num,
                    known_steps,
                    f"{prefix}.preconditions",
                ),
            )

        # Required: touches
        if "touches" not in step:
            errors.append(
                f"{prefix}: missing required 'touches' field " "(use empty list [] if the step touches no sensitive categories)",
            )
        elif not isinstance(step["touches"], list):
            errors.append(f"{prefix}.touches: must be a list of strings")
        else:
            for j, tag in enumerate(step["touches"]):
                if not isinstance(tag, str):
                    errors.append(
                        f"{prefix}.touches[{j}]: must be a string, got {type(tag).__name__}",
                    )

        # Required: recovery
        if "recovery" not in step:
            errors.append(
                f"{prefix}: missing required 'recovery' field " "(use a trivial branch like " '{"if": "(no failure expected)", "then": "proceed"} ' "if no failure path applies)",
            )
        else:
            errors.extend(
                validate_recovery_node(step["recovery"], f"{prefix}.recovery"),
            )

        # Optional: constraints
        constraints = step.get("constraints")
        if constraints is not None:
            if not isinstance(constraints, list):
                errors.append(f"{prefix}.constraints: must be a list of strings")
            else:
                for j, c in enumerate(constraints):
                    if not isinstance(c, str):
                        errors.append(
                            f"{prefix}.constraints[{j}]: must be a string, " f"got {type(c).__name__}",
                        )

        # Optional: approved_action + rollback rule
        aa = step.get("approved_action")
        if aa is not None:
            if not isinstance(aa, dict):
                errors.append(f"{prefix}.approved_action: must be a dict")
            else:
                for field in ("goal_id", "tool", "args"):
                    if field not in aa:
                        errors.append(
                            f"{prefix}.approved_action: missing '{field}'",
                        )

                # Rollback rule: required on action, forbidden elsewhere
                rollback_present = "rollback" in aa
                if kind == "action":
                    if not rollback_present:
                        errors.append(
                            f"{prefix}.approved_action: 'rollback' is required on "
                            "kind:action steps. Specify a rollback action spec "
                            "(dict with tool+args) OR explicit null for truly "
                            "irreversible actions.",
                        )
                    else:
                        rollback = aa["rollback"]
                        if rollback is not None:
                            errors.extend(
                                _validate_action_spec(
                                    rollback,
                                    f"{prefix}.approved_action.rollback",
                                ),
                            )
                elif kind is not None and rollback_present:
                    errors.append(
                        f"{prefix}.approved_action: 'rollback' is only " f"allowed on kind:action steps (this step is kind:{kind})",
                    )

    return errors


def extract_json(text: str) -> dict[str, Any]:
    """Extract JSON dict from text, handling fenced code blocks."""
    # Try bare JSON first
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)

    # Try ```json fenced block
    match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1).strip())

    # Try finding first { to last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError("No valid JSON object found in input")


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <path_to_json_file>", file=sys.stderr)
        return 1

    filepath = sys.argv[1]
    try:
        with open(filepath) as f:
            content = f.read()
    except FileNotFoundError:
        print(f"FAIL: file not found: {filepath}", file=sys.stderr)
        return 1

    try:
        data = extract_json(content)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"FAIL: could not parse JSON: {e}", file=sys.stderr)
        return 1

    errors = validate_plan(data)
    if errors:
        print("FAIL: validation errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
