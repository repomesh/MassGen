"""Standalone MCP server that exposes the MassGen submit_checklist tool.

This allows CLI-based backends (Codex) to use the checklist-gated voting
tool as a native MCP tool call.  The server reads checklist configuration
and mutable state from a JSON specs file written by the orchestrator.

The server re-reads the specs file on every tool call so the orchestrator
can update state (remaining budget, has_existing_answers) between rounds
without restarting the server process.

Usage (launched by backend via config.toml):
    fastmcp run massgen/mcp_tools/checklist_tools_server.py:create_server -- \
        --specs /path/to/checklist_specs.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

import fastmcp

from massgen.mcp_tools.planning.planning_dataclasses import normalize_task_execution

logger = logging.getLogger(__name__)

SERVER_NAME = "massgen_checklist"


def _normalize_task_execution_for_item(item: dict[str, Any], default_mode: str = "inline") -> dict[str, Any]:
    """Return canonical execution metadata for a task-plan item."""
    metadata = item.get("metadata")
    item_metadata = metadata if isinstance(metadata, dict) else {}
    return normalize_task_execution(
        item.get("execution") or item_metadata.get("execution"),
        subagent_id=item.get("subagent_id") or item_metadata.get("subagent_id"),
        subagent_name=item.get("subagent_name") or item_metadata.get("subagent_name"),
        default_mode=default_mode,
    )


def _resolve_hook_middleware() -> Any:
    """Return hook middleware class in both package and file-path launch modes."""
    try:
        from massgen.mcp_tools.hook_middleware import MassGenHookMiddleware

        return MassGenHookMiddleware
    except ImportError:
        pass

    try:
        from .hook_middleware import MassGenHookMiddleware

        return MassGenHookMiddleware
    except ImportError:
        pass

    # fastmcp file-path launches can drop package context; add repo root explicitly.
    project_root = str(Path(__file__).resolve().parents[2])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from massgen.mcp_tools.hook_middleware import MassGenHookMiddleware

    return MassGenHookMiddleware


async def create_server() -> fastmcp.FastMCP:
    """Factory function to create MCP server from checklist specs."""
    parser = argparse.ArgumentParser(description="MassGen Checklist MCP Server")
    parser.add_argument(
        "--specs",
        type=str,
        required=True,
        help="Path to JSON file containing checklist specs and state",
    )
    parser.add_argument(
        "--hook-dir",
        type=str,
        default=None,
        help="Optional path to directory for hook IPC files (PostToolUse injection).",
    )
    args = parser.parse_args()

    mcp = fastmcp.FastMCP(SERVER_NAME)

    # Attach hook middleware for PostToolUse injection if hook_dir is configured
    if args.hook_dir:
        MassGenHookMiddleware = _resolve_hook_middleware()
        mcp.add_middleware(MassGenHookMiddleware(Path(args.hook_dir)))
        logger.info("Hook middleware attached (hook_dir=%s)", args.hook_dir)
    specs_path = Path(args.specs)

    initial_specs = _read_specs(specs_path)
    injection_dir = initial_specs.get("state", {}).get("planning_injection_dir")
    _register_checklist_tool(mcp, specs_path, injection_dir=injection_dir)

    logger.info(f"Checklist MCP server ready (specs: {specs_path})")
    return mcp


def _read_specs(specs_path: Path) -> dict[str, Any]:
    """Read specs file, returning empty dict on error."""
    try:
        with open(specs_path) as f:
            return json.load(f)
    except Exception as exc:
        logger.error(f"Failed to read checklist specs: {exc}")
        return {}


def build_round_evaluator_task_mode_redirect(state: dict[str, Any]) -> str | None:
    """Return a redirect message when post-evaluator tasks are already injected."""
    if not bool(state.get("round_evaluator_auto_injected", False)):
        return None

    critique_path = str(state.get("round_evaluator_primary_artifact_path") or "").strip()
    verdict_path = str(state.get("round_evaluator_verdict_artifact_path") or "").strip()
    next_tasks_path = str(state.get("round_evaluator_next_tasks_artifact_path") or "").strip()
    objective = str(state.get("round_evaluator_objective") or "").strip()
    primary_strategy = str(state.get("round_evaluator_primary_strategy") or "").strip()
    why_this_strategy = str(state.get("round_evaluator_why_this_strategy") or "").strip()
    strategy_mode = str(state.get("round_evaluator_strategy_mode") or "").strip()
    incremental_override_reason = str(state.get("round_evaluator_incremental_override_reason") or "").strip()
    success_contract = state.get("round_evaluator_success_contract")
    deprioritize_raw = state.get("round_evaluator_deprioritize_or_remove")
    deprioritize = [str(item).strip() for item in deprioritize_raw or [] if str(item).strip()] if isinstance(deprioritize_raw, list) else []

    parts = [
        "The round evaluator has already finished and auto-injected your next tasks.",
        "`get_task_plan` is the source of truth.",
        "Implement and verify those tasks, then call `new_answer`.",
        "Do not call `submit_checklist` or `draft_approach` here.",
        "Do not write a second diagnostic report.",
    ]
    if objective:
        parts.append(f"Chosen objective: {objective}.")
    if primary_strategy:
        parts.append(f"Chosen strategy: {primary_strategy}.")
    if why_this_strategy:
        parts.append(f"Why this strategy: {why_this_strategy}.")
    if strategy_mode:
        parts.append(f"Strategy mode: {strategy_mode}.")
    if incremental_override_reason:
        parts.append(f"Incremental override reason: {incremental_override_reason}.")
    if deprioritize:
        parts.append(f"Deprioritize or remove: {', '.join(deprioritize)}.")
    if isinstance(success_contract, dict):
        outcome_statement = str(success_contract.get("outcome_statement") or "").strip()
        quality_bar = str(success_contract.get("quality_bar") or "").strip()
        fail_if_any = [str(item).strip() for item in success_contract.get("fail_if_any", []) if str(item).strip()]
        required_evidence = [str(item).strip() for item in success_contract.get("required_evidence", []) if str(item).strip()]
        if outcome_statement:
            parts.append(f"Success contract outcome: {outcome_statement}.")
        if quality_bar:
            parts.append(f"Success contract quality bar: {quality_bar}.")
        if fail_if_any:
            parts.append(f"Still failing if any remain: {'; '.join(fail_if_any)}.")
        if required_evidence:
            parts.append(f"Required evidence: {'; '.join(required_evidence)}.")
    if critique_path:
        parts.append(f"Reference critique packet: {critique_path}.")
    if verdict_path:
        parts.append(f"Reference verdict metadata: {verdict_path}.")
    if next_tasks_path:
        parts.append(f"Reference next-task handoff: {next_tasks_path}.")
    return " ".join(parts)


def _extract_score(entry: Any) -> int:
    """Extract numeric score from either int or {"score": int, "reasoning": str}."""
    if isinstance(entry, dict):
        return entry.get("score", 0)
    if isinstance(entry, (int, float)):
        return int(entry)
    return 0


def _criterion_sort_key(cid: str) -> tuple[int, str]:
    """Sort criterion IDs by their numeric suffix (E1, E2, ..., E10) when present."""
    digits = "".join(ch for ch in cid if ch.isdigit())
    return (int(digits) if digits else 1_000_000, cid)


def extract_criterion_feedback(scores: Any, item_prefix: str = "E") -> dict[str, str]:
    """Return {criterion_id: reasoning} from submitted checklist scores.

    Handles both the flat shape ``{"E1": {"score": N, "reasoning": "..."}}`` and
    the per-agent shape ``{"agent1.1": {"E1": {...}}, ...}``. For per-agent
    submissions the reasoning attached to the LOWEST score per criterion is kept
    (the most diagnostic signal for what to fix next round). Entries without a
    usable reasoning string are skipped. Returns {} for non-dict input.
    """
    if not isinstance(scores, dict) or not scores:
        return {}

    best: dict[str, tuple[int, str]] = {}

    def _consider(cid: str, entry: Any) -> None:
        if not isinstance(entry, dict):
            return
        reasoning = str(entry.get("reasoning") or "").strip()
        if not reasoning:
            return
        score = _extract_score(entry)
        if cid not in best or score < best[cid][0]:
            best[cid] = (score, reasoning)

    if _is_per_agent_scores(scores, item_prefix):
        for agent_scores in scores.values():
            if isinstance(agent_scores, dict):
                for cid, entry in agent_scores.items():
                    _consider(cid, entry)
    else:
        for cid, entry in scores.items():
            _consider(cid, entry)

    return {cid: reasoning for cid, (_score, reasoning) in best.items()}


def format_criterion_feedback_memo(
    feedback: dict[str, str],
    failed_ids: list[str] | None = None,
) -> str:
    """Render per-criterion feedback into a round-start memo (Reflexion gradient).

    Returns "" when there is no feedback. Failed criteria are marked so the next
    round's generator knows which gaps are blocking, not just which exist.
    """
    if not feedback:
        return ""
    failed = set(failed_ids or [])
    lines = [
        "<CRITERION FEEDBACK from last round — address these gaps before your next answer>",
    ]
    for cid in sorted(feedback, key=_criterion_sort_key):
        marker = " (FAILED)" if cid in failed else ""
        lines.append(f"- {cid}{marker}: {feedback[cid]}")
    lines.append("<END OF CRITERION FEEDBACK>")
    return "\n".join(lines)


def _find_plateaued_criteria(
    current_items: list[dict],
    checklist_history: list[dict],
    items: list[str] | None = None,
    item_categories: dict[str, str] | None = None,
    min_rounds: int = 2,
) -> list[dict]:
    """Return detail dicts for criteria whose scores haven't improved.

    Each returned dict contains:
    - id: criterion ID (e.g. "E1")
    - text: criterion text (from items list)
    - category: primary/standard/stretch (legacy: must/should/could)
    - score_history: list of scores across rounds (prior + current)
    - current_score: latest score

    This rich detail is designed to be passed directly to quality/novelty
    subagents so they have full context about what's stuck and by how much.
    """
    if len(checklist_history) < min_rounds:
        return []
    items = items or []
    item_categories = item_categories or {}
    current_by_id = {d["id"]: d["score"] for d in current_items}
    plateaued = []
    for cid, current_score in current_by_id.items():
        stuck = True
        score_history = []
        for entry in checklist_history[-min_rounds:]:
            prev_items = {d["id"]: d["score"] for d in entry.get("items_detail", [])}
            prev_score = prev_items.get(cid)
            score_history.append(prev_score)
            if prev_score is None or current_score > prev_score + 1:
                stuck = False
                break
        if stuck:
            idx = int(cid[1:]) - 1
            score_history.append(current_score)
            plateaued.append(
                {
                    "id": cid,
                    "text": items[idx] if idx < len(items) else cid,
                    "category": item_categories.get(cid, "unknown"),
                    "score_history": score_history,
                    "current_score": current_score,
                },
            )
    return plateaued


_VALID_IMPACTS = {"transformative", "structural", "incremental"}
_MAX_DIAGNOSTIC_ARTIFACT_PATHS = 20


def _extract_absolute_paths_from_text(text: str, max_paths: int = _MAX_DIAGNOSTIC_ARTIFACT_PATHS) -> list[str]:
    """Extract unique absolute Unix paths from free-form text.

    This is used to surface artifact/report paths already captured by evaluator
    reports so novelty/quality subagents can inspect evidence directly instead
    of re-running evaluation.
    """
    if not text or max_paths <= 0:
        return []

    # Match path-like tokens beginning with "/" while avoiding URL "//" segments.
    raw_tokens = re.findall(r"(?<![:/])(/[^\s`\"'<>|]+)", text)
    seen: set[str] = set()
    extracted: list[str] = []
    for token in raw_tokens:
        cleaned = token.rstrip(".,;:!?)]}\"'")
        if not cleaned:
            continue
        if cleaned.startswith("//"):
            continue
        if not Path(cleaned).is_absolute():
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        extracted.append(cleaned)
        if len(extracted) >= max_paths:
            break
    return extracted


def _normalize_evaluation_input_packet(
    latest_evaluation: dict[str, Any] | None,
    failed_criteria: list[str],
) -> dict[str, Any]:
    """Return a stable, JSON-serializable evaluation packet for subagent handoff."""
    source = latest_evaluation if isinstance(latest_evaluation, dict) else {}
    packet: dict[str, Any] = {
        "failed_criteria": list(source.get("failed_criteria") or failed_criteria or []),
        "failing_criteria_detail": list(source.get("failing_criteria_detail") or []),
        "plateaued_criteria": list(source.get("plateaued_criteria") or []),
        "checklist_explanation": str(source.get("checklist_explanation") or ""),
        "diagnostic_report_path": str(source.get("diagnostic_report_path") or ""),
        "diagnostic_report_artifact_paths": [],
    }
    raw_paths = source.get("diagnostic_report_artifact_paths") or []
    if isinstance(raw_paths, list):
        clean_paths: list[str] = []
        for path_value in raw_paths:
            path_text = str(path_value).strip()
            if not path_text:
                continue
            if path_text not in clean_paths:
                clean_paths.append(path_text)
            if len(clean_paths) >= _MAX_DIAGNOSTIC_ARTIFACT_PATHS:
                break
        packet["diagnostic_report_artifact_paths"] = clean_paths
    return packet


def _build_novelty_quality_task_templates(evaluation_input: dict[str, Any]) -> dict[str, str]:
    """Create copy-ready task templates for novelty and quality_rethinking subagents."""
    payload = json.dumps(evaluation_input, indent=2, ensure_ascii=False)
    shared_preamble = (
        "Use the Evaluation Input (verbatim) block below as source of truth. "
        "Do NOT re-evaluate, re-score, or repeat checklist analysis.\n"
        "If diagnostic report/artifact paths are present, inspect them first and ground your proposals in that evidence.\n\n"
        "Evaluation Input (verbatim):\n"
    )
    novelty_template = "You are the novelty subagent. Propose 2-3 fundamentally different directions to break the plateau.\n" + shared_preamble + payload
    quality_template = "You are the quality_rethinking subagent. Propose 3-5 targeted craft upgrades within current structure.\n" + shared_preamble + payload
    return {
        "novelty_task_template": novelty_template,
        "quality_rethinking_task_template": quality_template,
    }


def _normalize_improvement_entry(entry: Any) -> dict[str, Any]:
    """Normalize an improvement entry to {"plan": str, "sources": list, "impact": str}."""
    if isinstance(entry, str):
        return {"plan": entry, "sources": [], "impact": "incremental"}
    if isinstance(entry, dict):
        impact = entry.get("impact", "incremental")
        if impact not in _VALID_IMPACTS:
            impact = "incremental"
        return {
            "plan": str(entry.get("plan", "")),
            "sources": list(entry.get("sources", [])),
            "impact": impact,
        }
    return {"plan": str(entry), "sources": [], "impact": "incremental"}


def _normalize_preserve_entry(entry: Any) -> dict[str, str]:
    """Normalize a preserve entry to {"what": str, "source": str}."""
    if isinstance(entry, str):
        return {"what": entry, "source": ""}
    if isinstance(entry, dict):
        return {
            "what": str(entry.get("what", "")),
            "source": str(entry.get("source", "")),
        }
    return {"what": str(entry), "source": ""}


def _all_sources_are_fresh(improvements: dict[str, Any]) -> bool:
    """Return True when every improvement entry uses only 'fresh'/'new' sources."""
    _FRESH_SENTINELS = {"fresh", "new"}
    for entries in improvements.values():
        for entry in entries:
            norm = _normalize_improvement_entry(entry)
            sources = norm.get("sources", [])
            if not sources or not all(s.lower().strip() in _FRESH_SENTINELS for s in sources):
                return False
    return True


def evaluate_draft_approach(
    improvements: dict[str, Any],
    failed_criteria: list[str],
    items: list[str],
    all_criteria_ids: list[str] | None = None,
    preserve: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    latest_evaluation: dict[str, Any] | None = None,
    vision: str | None = None,
) -> dict[str, Any]:
    """Validate that improvements cover all failing criteria and preserve strengths."""
    if not isinstance(improvements, dict):
        return {"valid": False, "error": "improvements must be a dict mapping criterion IDs to lists"}

    if not failed_criteria:
        return {"valid": False, "error": "No failed criteria to improve"}

    missing = [cid for cid in failed_criteria if cid not in improvements]
    empty = [cid for cid in failed_criteria if cid in improvements and not improvements[cid]]

    if missing or empty:
        issues = []
        if missing:
            issues.append(f"Missing improvements for: {', '.join(missing)}")
        if empty:
            issues.append(f"Empty improvements for: {', '.join(empty)}")
        return {
            "valid": False,
            "error": "; ".join(issues),
            "missing_criteria": missing,
            "empty_criteria": empty,
            "failed_criteria": failed_criteria,
        }

    # --- Preserve validation (only when all_criteria_ids is provided) ---
    preserve = preserve or {}
    normalized_preserve: dict[str, dict[str, str]] = {}

    if all_criteria_ids is not None:
        # Require at least one preserve entry when criteria exist —
        # UNLESS all improvements use only "fresh" sources (starting over).
        if all_criteria_ids and not preserve and not _all_sources_are_fresh(improvements):
            return {
                "valid": False,
                "error": ("Preserve is required: specify what to protect from regression. " f"Criteria available: {', '.join(all_criteria_ids)}"),
            }

        # Validate each preserve entry
        for cid, entry in preserve.items():
            if cid not in all_criteria_ids:
                return {
                    "valid": False,
                    "error": f"Preserve key {cid} is not a valid criterion ID. Valid: {', '.join(all_criteria_ids)}",
                }
            norm = _normalize_preserve_entry(entry)
            if not norm["what"].strip():
                return {
                    "valid": False,
                    "error": f"Preserve entry for {cid} has empty 'what' — describe what to protect.",
                }
            normalized_preserve[cid] = norm
    else:
        # Backward compat: normalize whatever was passed but don't enforce
        for cid, entry in preserve.items():
            normalized_preserve[cid] = _normalize_preserve_entry(entry)

    # --- Impact gate: require at least min_non_incremental (structural/transformative) ---
    _state = state or {}
    improvements_cfg = _state.get("improvements", {})
    min_transformative = improvements_cfg.get("min_transformative", 0)
    min_structural = improvements_cfg.get("min_structural", 0)
    min_non_incremental = improvements_cfg.get("min_non_incremental", 1)

    all_entries = [_normalize_improvement_entry(e) for entries in improvements.values() for e in entries]
    transformative_count = sum(1 for e in all_entries if e.get("impact") == "transformative")
    structural_count = sum(1 for e in all_entries if e.get("impact") == "structural")
    non_incremental_count = transformative_count + structural_count

    impact_failures = []
    if transformative_count < min_transformative:
        impact_failures.append(f"transformative: {transformative_count}/{min_transformative}")
    if structural_count < min_structural:
        impact_failures.append(f"structural: {structural_count}/{min_structural}")
    if non_incremental_count < min_non_incremental:
        impact_failures.append(
            f"non-incremental combined: {non_incremental_count}/{min_non_incremental}",
        )

    if impact_failures:
        return {
            "valid": False,
            "error": (
                f"Improvement impact requirements not met ({', '.join(impact_failures)}). "
                "A round at this cost needs bolder changes. Consider spawning a novelty or "
                "quality_rethinking subagent in background to generate stronger directions, "
                "then revise your proposal."
            ),
        }

    # --- Build task plan: vision preamble, improvements, then verify_preserve ---
    task_plan: list[dict[str, Any]] = []

    # Vision preamble: guides execution toward the ideal, not just fixing what's broken
    if vision and isinstance(vision, str) and vision.strip():
        task_plan.append(
            {
                "type": "vision",
                "description": vision.strip(),
                "priority": "high",
                "execution": {"mode": "inline"},
            },
        )

    answer_count = _state.get("agent_answer_count", 0)
    try:
        answer_count = int(answer_count)
    except (TypeError, ValueError):
        answer_count = 0
    spawn_novelty = bool(_state.get("enable_novelty_on_iteration")) and answer_count >= 1
    spawn_quality_rethinking = bool(_state.get("enable_quality_rethink_on_iteration")) and answer_count >= 1
    should_inject_iteration_spawn = bool(_state.get("subagents_enabled")) and (spawn_novelty or spawn_quality_rethinking)

    if should_inject_iteration_spawn and failed_criteria:
        evaluation_input = _normalize_evaluation_input_packet(latest_evaluation, failed_criteria)
        task_plan.append(
            {
                "id": "novelty_quality_spawn",
                "type": "novelty_quality_spawn",
                "description": (
                    "Spawn novelty and/or quality_rethinking subagents in background "
                    "IMMEDIATELY (before implementing improvements). Use the provided "
                    "`subagent_task_templates` and paste `evaluation_input` verbatim so "
                    "subagents can propose improvements without re-evaluating. Integrate "
                    "their output before submitting your new answer. If neither type is "
                    "available, skip this task."
                ),
                "priority": "high",
                "verification": "Novelty/quality subagents spawned via spawn_subagents(background=True)",
                "verification_method": "list_subagents() shows spawned novelty/quality subagents",
                "metadata": {
                    "type": "novelty_quality_spawn",
                    "failing_criteria": list(failed_criteria),
                    "spawn_novelty": spawn_novelty,
                    "spawn_quality_rethinking": spawn_quality_rethinking,
                    "evaluation_input": evaluation_input,
                    "subagent_task_templates": _build_novelty_quality_task_templates(evaluation_input),
                },
            },
        )

    # Improvement entries
    _subagents_on = bool(_state.get("subagents_enabled"))
    for cid in failed_criteria:
        criterion_idx = int(cid[1:]) - 1
        criterion_text = items[criterion_idx] if criterion_idx < len(items) else cid
        for imp_entry in improvements[cid]:
            norm = _normalize_improvement_entry(imp_entry)
            task_entry = {
                "type": "improve",
                "criterion_id": cid,
                "criterion": criterion_text,
                "plan": norm["plan"],
                "sources": norm["sources"],
                "impact": norm["impact"],
                # Keep backward-compat "improvement" key
                "improvement": norm["plan"],
            }
            if _subagents_on:
                task_entry["execution"] = {"mode": "delegate", "subagent_type": "builder"}
            else:
                task_entry["execution"] = {"mode": "inline"}
            task_plan.append(task_entry)

    # Single verify_preserve checkpoint at the END (not N individual preserve rows)
    if normalized_preserve:
        preserve_items = [{"criterion_id": cid, "what": p["what"], "source": p["source"]} for cid, p in normalized_preserve.items()]
        verify_description = (
            "Before submitting: verify these strengths haven't regressed and "
            "that earlier correctness fixes still hold after later changes — "
            "confirm each preserved item is present in the actual output, and "
            "that passing criteria scores haven't dropped."
        )
        verify_task: dict[str, Any] = {
            "type": "verify_preserve",
            "description": verify_description,
            "items": preserve_items,
            "priority": "high",
            "execution": {"mode": "inline"},
        }
        task_plan.append(verify_task)

    _base_msg = (
        f"Improvements validated for {len(failed_criteria)} criteria. "
        f"{len(normalized_preserve)} criteria marked for preservation. "
        "Add each item from task_plan to your task plan tool, then "
        "execute them. Do correctness-critical tasks first when present, "
        "then the remaining higher-order work. The verify_preserve item at "
        "the end is a final guardrail — confirm preserved strengths are "
        "intact and that earlier correctness fixes still hold after later "
        "changes before submitting. Do not defer blocker correctness fixes "
        "in favor of easier polish."
    )
    if _subagents_on:
        _base_msg += (
            "\n\n**DELEGATION REQUIRED**: All improve tasks are marked "
            "delegate — you MUST spawn builder subagents for them. Do NOT "
            "implement improvements inline. Group related criteria (those "
            "touching the same file or surface) into builder subagents, "
            "max ~2-3 criteria per builder. Primary criteria get their own "
            "builder. Spawn all builders in parallel via a single "
            "spawn_subagents call with background=True, then merge their "
            "outputs before submitting."
        )
    result: dict[str, Any] = {
        "valid": True,
        "task_plan": task_plan,
        "message": _base_msg,
    }
    if normalized_preserve:
        result["preserve"] = normalized_preserve
    return result


def _resolve_allowed_external_report_paths(state: dict[str, Any]) -> set[Path]:
    """Return exact external report paths the checklist server may accept."""
    allowed: set[Path] = set()

    explicit = state.get("allowed_external_report_paths")
    if isinstance(explicit, list):
        for path_value in explicit:
            path_text = str(path_value or "").strip()
            if not path_text:
                continue
            allowed.add(Path(path_text).resolve())

    critique_path = str(state.get("round_evaluator_primary_artifact_path") or "").strip()
    if critique_path:
        allowed.add(Path(critique_path).resolve())

    return allowed


def _resolve_report_file(report_path: str, state: dict[str, Any]) -> tuple[Path | None, str | None]:
    """Resolve report path to an allowed absolute path."""
    if report_path is None:
        raw_path = ""
    elif isinstance(report_path, str):
        raw_path = report_path.strip()
    else:
        return None, "Invalid `report_path`: expected a string path."

    if not raw_path:
        return None, "Missing `report_path`."

    workspace_root = state.get("workspace_path")
    workspace = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = (workspace / candidate).resolve()
    else:
        candidate = candidate.resolve()

    try:
        candidate.relative_to(workspace)
    except ValueError:
        if candidate in _resolve_allowed_external_report_paths(state):
            return candidate, None
        return None, f"Report path must stay inside workspace ({workspace}) unless it is an allowed external evaluator artifact."

    return candidate, None


_DIAGNOSTIC_REPORT_MIN_LENGTH = 100


def _evaluate_gap_report(report_path: str, state: dict[str, Any]) -> dict[str, Any]:
    """Check diagnostic report file existence, substance, and capture content.

    When ``require_diagnostic_report`` is True in state, the report is gated:
    missing, empty, or trivially short reports cause ``passed=False``, which
    the caller uses to override the verdict to iterate. No keyword or
    heuristic matching is performed — the system prompt tells agents what
    sections to write, and we trust that (matching GEPA's approach).

    Report content is captured in ``result["content"]`` for logging and
    potential forwarding to future rounds.
    """
    require_report = bool(state.get("require_diagnostic_report", False))
    if report_path is None:
        report_path_text = ""
    elif isinstance(report_path, str):
        report_path_text = report_path.strip()
    else:
        report_path_text = ""

    result: dict[str, Any] = {
        "provided": bool(report_path_text),
        "path": report_path_text,
        "passed": True,  # default: pass (backward compat when gate inactive)
        "gate_active": require_report,
        "content": None,
        "issues": [],
    }

    if not result["provided"]:
        if require_report:
            result["passed"] = False
            result["issues"].append(
                "Diagnostic report is required before submitting scores. "
                "Write a markdown diagnostic report covering Failure Patterns, "
                "Root Causes, and Goal Alignment, then provide its path via report_path.",
            )
        return result

    resolved, error = _resolve_report_file(report_path, state)
    if error:
        result["issues"].append(error)
        if require_report:
            result["passed"] = False
        return result
    if resolved is None:
        if require_report:
            result["passed"] = False
        return result

    result["resolved_path"] = str(resolved)
    if not resolved.exists():
        result["issues"].append(f"Report file not found: {resolved}")
        if require_report:
            result["passed"] = False
        return result
    if not resolved.is_file():
        result["issues"].append(f"Report path is not a file: {resolved}")
        if require_report:
            result["passed"] = False
        return result

    try:
        report_text = resolved.read_text(encoding="utf-8")
    except Exception as exc:
        result["issues"].append(f"Unable to read report file: {exc}")
        if require_report:
            result["passed"] = False
        return result

    if not report_text.strip():
        result["issues"].append("Report file is empty.")
        if require_report:
            result["passed"] = False
        return result

    result["file_exists"] = True
    result["content"] = report_text
    result["artifact_paths"] = _extract_absolute_paths_from_text(report_text)

    has_multimodal = bool(state.get("has_multimodal_tools", False))
    min_length = 300 if has_multimodal else _DIAGNOSTIC_REPORT_MIN_LENGTH

    if require_report and len(report_text.strip()) < min_length:
        result["passed"] = False
        msg = "Report is too short to contain meaningful diagnostic analysis. " "Include Failure Patterns, Root Causes, and Goal Alignment sections."
        if has_multimodal:
            msg += " When visual evaluation tools are available, your diagnostic " "report must include specific findings from read_media analysis."
        result["issues"].append(msg)

    return result


def _is_per_agent_scores(scores: dict[str, Any], item_prefix: str) -> bool:
    """Return True if scores is per-agent format (keyed by agent label, not E/T-prefixed)."""
    if not scores:
        return False
    return not any(k.startswith(item_prefix) or k.startswith("T") or k.startswith("E") for k in scores)


def _extract_submitted_agent_labels(scores_payload: Any, item_prefix: str = "E") -> set[str]:
    """Extract top-level agent labels from submit_checklist scores payload."""
    if not isinstance(scores_payload, dict) or not scores_payload:
        return set()
    top_level_keys = {str(k) for k in scores_payload.keys()}
    if any(k.startswith(item_prefix) or k.startswith("E") or k.startswith("T") for k in top_level_keys):
        return set()
    return top_level_keys


def _normalize_pending_recheck_labels(raw_labels: Any) -> set[str]:
    """Normalize pending checklist recheck labels from state payloads."""
    if isinstance(raw_labels, str):
        label = raw_labels.strip()
        return {label} if label else set()
    if isinstance(raw_labels, (list, tuple, set)):
        normalized: set[str] = set()
        for raw in raw_labels:
            label = str(raw).strip()
            if label:
                normalized.add(label)
        return normalized
    return set()


def _extract_flat_scores(
    per_agent: dict[str, Any],
    item_prefix: str,
    n_items: int,
) -> tuple[str, dict[str, Any], dict[str, dict[str, int]]]:
    """Find the best agent by aggregate score and return (best_label, flat_scores, per_agent_summary).

    per_agent_summary maps agent_label -> {criterion: score} for inclusion in the response.
    """
    per_agent_summary: dict[str, dict[str, int]] = {}
    best_label = ""
    best_total = -1
    best_scores: dict[str, Any] = {}

    for agent_label, agent_scores in per_agent.items():
        if not isinstance(agent_scores, dict):
            continue
        total = sum(_extract_score(agent_scores.get(f"{item_prefix}{i+1}", agent_scores.get(f"E{i+1}", 0))) for i in range(n_items))
        summary = {f"{item_prefix}{i+1}": _extract_score(agent_scores.get(f"{item_prefix}{i+1}", agent_scores.get(f"E{i+1}", 0))) for i in range(n_items)}
        per_agent_summary[agent_label] = summary
        # Position-bias fix: break ties deterministically by label (lexicographically
        # smallest wins) rather than by dict iteration order, so the selected best
        # agent does not depend on submission/insertion order.
        if total > best_total or (total == best_total and (not best_label or agent_label < best_label)):
            best_total = total
            best_label = agent_label
            best_scores = agent_scores

    return best_label, best_scores, per_agent_summary


def _validation_error_payload(
    *,
    explanation: str,
    report_eval: dict[str, Any],
    required: int,
    error_code: str,
    incomplete_scores: bool = False,
    report_gate_triggered: bool = False,
) -> dict[str, Any]:
    """Build a standardized validation-error response payload."""
    payload: dict[str, Any] = {
        "status": "validation_error",
        "requires_resubmission": True,
        "error_code": error_code,
        "explanation": explanation,
        "incomplete_scores": bool(incomplete_scores),
        "true_count": 0,
        "required": required,
        "items": [],
        "failed_criteria": [],
        "plateaued_criteria": [],
        "report": report_eval,
        "report_gate_triggered": bool(report_gate_triggered),
    }
    return payload


def evaluate_checklist_submission(
    scores: dict[str, Any],
    report_path: str,
    items: list,
    state: dict[str, Any],
    checklist_history: list[dict] | None = None,
) -> dict[str, Any]:
    """Evaluate checklist submission and return verdict payload used by stdio + SDK."""
    terminate_action = state.get("terminate_action", "vote")
    iterate_action = state.get("iterate_action", "new_answer")
    has_existing_answers = state.get("has_existing_answers", False)
    required = state.get("required", len(items))
    cutoff = state.get("cutoff", 70)
    decomposition_mode = bool(state.get("decomposition_mode", False))
    current_answer_label = str(state.get("current_answer_label") or "").strip()

    # Determine item prefix: use E-prefix (new default), but accept T-prefix
    # submissions for backwards compatibility
    item_prefix = state.get("item_prefix", "E")

    # Detect per-agent format and normalise to flat scores for verdict logic.
    # Per-agent: {"agent1": {"E1": ..., "E2": ...}, "agent2": {...}}
    # Flat (legacy): {"E1": ..., "E2": ...}
    best_agent: str | None = None
    per_agent_scores: dict[str, dict[str, int]] | None = None
    available_agent_labels: list[str] = state.get("available_agent_labels") or []

    if not isinstance(scores, dict):
        report_eval = _evaluate_gap_report(report_path, state)
        return _validation_error_payload(
            explanation="Invalid `scores`: expected a JSON object.",
            report_eval=report_eval,
            required=required,
            error_code="scores_type_invalid",
        )

    if _is_per_agent_scores(scores, item_prefix):
        if decomposition_mode:
            if current_answer_label and isinstance(scores.get(current_answer_label), dict):
                scores = scores[current_answer_label]
            elif len(scores) == 1:
                only_scores = next(iter(scores.values()))
                if isinstance(only_scores, dict):
                    scores = only_scores
                else:
                    report_eval = _evaluate_gap_report(report_path, state)
                    return _validation_error_payload(
                        explanation=(
                            "Decomposition mode checklist evaluation must score your current "
                            "subtask output. Submit flat scores (`E1`, `E2`, ...) or provide "
                            f"your current answer label ({current_answer_label or 'current answer label'}) only."
                        ),
                        report_eval=report_eval,
                        required=required,
                        error_code="decomposition_scores_invalid",
                    )
            else:
                report_eval = _evaluate_gap_report(report_path, state)
                return _validation_error_payload(
                    explanation=(
                        "Decomposition mode checklist evaluation must score your current "
                        "subtask output, not rank all peer answers. Submit flat scores "
                        f"(`E1`, `E2`, ...) or provide only your current answer label ({current_answer_label or 'current answer label'})."
                    ),
                    report_eval=report_eval,
                    required=required,
                    error_code="decomposition_scores_invalid",
                )
        else:
            # Validate completeness for ALL agents before selecting best.
            expected_keys = {f"{item_prefix}{i+1}" for i in range(len(items))}
            incomplete_agents = []
            for agent_label, agent_scores in scores.items():
                if not isinstance(agent_scores, dict):
                    continue
                agent_keys = {k.replace("T", item_prefix, 1) if k.startswith("T") else k for k in agent_scores}
                missing = sorted(expected_keys - agent_keys)
                if missing:
                    incomplete_agents.append((agent_label, missing))
            if incomplete_agents and has_existing_answers:
                report_eval = _evaluate_gap_report(report_path, state)
                details = "; ".join(f"{a}: missing {', '.join(m)}" for a, m in incomplete_agents)
                return _validation_error_payload(
                    explanation=(f"Incomplete per-agent submission: {details}. " f"You must score ALL {len(items)} criteria for EVERY agent. " "Resubmit with complete scores."),
                    report_eval=report_eval,
                    required=required,
                    error_code="incomplete_agent_criteria",
                    incomplete_scores=True,
                )
            # Validate all available agents are covered when labels are known.
            if available_agent_labels and has_existing_answers:
                missing_agents = sorted(set(available_agent_labels) - set(scores.keys()))
                if missing_agents:
                    report_eval = _evaluate_gap_report(report_path, state)
                    return _validation_error_payload(
                        explanation=(
                            f"Missing scores for available agents: {', '.join(missing_agents)}. "
                            "You must score ALL agents you have context for: "
                            f"{', '.join(sorted(available_agent_labels))}. "
                            "Resubmit with per-agent scores covering every agent."
                        ),
                        report_eval=report_eval,
                        required=required,
                        error_code="missing_agent_scores",
                        incomplete_scores=True,
                    )
            best_agent, scores, per_agent_scores = _extract_flat_scores(scores, item_prefix, len(items))
    elif len(available_agent_labels) >= 2 and has_existing_answers and not decomposition_mode:
        # Flat format submitted but multiple agents are available — require per-agent format.
        report_eval = _evaluate_gap_report(report_path, state)
        return _validation_error_payload(
            explanation=(
                f"You submitted flat scores but you have {len(available_agent_labels)} agents available "
                f"({', '.join(sorted(available_agent_labels))}). "
                "Use per-agent format to score ALL available agents: "
                f'{{"{available_agent_labels[0]}": {{"E1": {{"score": N, "reasoning": "..."}}, ...}}, '
                f'"{available_agent_labels[1]}": {{...}}}}.'
            ),
            report_eval=report_eval,
            required=required,
            error_code="flat_scores_disallowed",
            incomplete_scores=True,
        )

    # Reject incomplete submissions — agent must score ALL criteria
    expected_keys = {f"{item_prefix}{i+1}" for i in range(len(items))}
    submitted_keys = set(scores.keys())
    # Accept both E-prefix and T-prefix
    submitted_normalized = set()
    for k in submitted_keys:
        if k.startswith("T"):
            submitted_normalized.add(k.replace("T", item_prefix, 1))
        elif k.startswith("E"):
            submitted_normalized.add(k)
        else:
            submitted_normalized.add(k)
    missing_keys = sorted(expected_keys - submitted_normalized)

    if missing_keys and has_existing_answers:
        report_eval = _evaluate_gap_report(report_path, state)
        return _validation_error_payload(
            explanation=(
                f"Incomplete submission: missing scores for {', '.join(missing_keys)}. "
                f"You must score ALL {len(items)} criteria ({item_prefix}1-{item_prefix}{len(items)}). "
                "Resubmit with scores for every criterion."
            ),
            report_eval=report_eval,
            required=required,
            error_code="missing_criteria_scores",
            incomplete_scores=True,
        )

    items_detail = []
    true_count = 0
    for i, _item_text in enumerate(items):
        key = f"{item_prefix}{i+1}"
        # Accept both E-prefix and T-prefix submissions for backwards compat
        entry = scores.get(key, scores.get(f"T{i+1}", scores.get(f"E{i+1}", 0)))
        score = _extract_score(entry)
        passed = score >= cutoff
        if passed:
            true_count += 1
        items_detail.append({"id": key, "score": score, "passed": passed})

    report_eval = _evaluate_gap_report(report_path, state)

    plateaued_failing: list[dict] = []

    if not has_existing_answers:
        verdict = iterate_action
        explanation = f"First answer — no existing answers to evaluate. Verdict: {verdict}."
    else:
        # Verdict determined solely by item scores
        verdict = terminate_action if true_count >= required else iterate_action
        failed_ids = [d["id"] for d in items_detail if not d["passed"]]
        failed_set = set(failed_ids)

        if verdict == iterate_action:
            explanation = f"{true_count} of {len(items)} items passed (required: {required}). " f"Verdict: {verdict}. "
            if failed_ids:
                explanation += f"Items that need improvement: {', '.join(failed_ids)}. "

            # Per-criterion plateau → targeted subagent guidance
            _item_categories = state.get("item_categories", {})
            plateaued_all = _find_plateaued_criteria(
                items_detail,
                checklist_history or [],
                items=items,
                item_categories=_item_categories,
                min_rounds=2,
            )
            plateaued_failing = [d for d in plateaued_all if d["id"] in failed_set]

            _quality_rethinking_enabled = state.get(
                "quality_rethinking_subagent_enabled",
                False,
            )
            _novelty_enabled = state.get("novelty_subagent_enabled", False)
            _answer_count = state.get("agent_answer_count", 0)
            try:
                _answer_count = int(_answer_count)
            except (TypeError, ValueError):
                _answer_count = 0
            _iter_novelty_enabled = bool(state.get("enable_novelty_on_iteration")) and _answer_count >= 1
            _iter_quality_enabled = bool(state.get("enable_quality_rethink_on_iteration")) and _answer_count >= 1
            _spawn_novelty = _novelty_enabled and _iter_novelty_enabled
            _spawn_quality = _quality_rethinking_enabled and _iter_quality_enabled

            if has_existing_answers and plateaued_failing:
                # Build score trajectory strings like "E5 (should, scores: 5→6→6)"
                trajectory_parts = []
                for pd in plateaued_failing:
                    scores_str = "\u2192".join(str(s) for s in pd["score_history"])
                    trajectory_parts.append(
                        f"{pd['id']} ({pd['category']}, scores: {scores_str})",
                    )
                plateaued_str = ", ".join(trajectory_parts)
                if _quality_rethinking_enabled and _novelty_enabled:
                    explanation += (
                        f"Criteria {plateaued_str} have plateaued. "
                        "Spawn a quality_rethinking subagent AND a novelty subagent "
                        "side-by-side in background \u2014 pass each the "
                        "plateaued_criteria detail from this result (it contains "
                        "criterion text, category, and full score history). "
                        "Meanwhile, proceed with draft_approach and start "
                        "implementing. Integrate subagent proposals when they return. "
                    )
                elif _quality_rethinking_enabled:
                    explanation += (
                        f"Criteria {plateaued_str} have plateaued. "
                        "Spawn a quality_rethinking subagent in background \u2014 pass "
                        "it the plateaued_criteria detail from this result. It will "
                        "propose per-element craft improvements targeted at raising "
                        "these specific scores. "
                    )
                elif _novelty_enabled:
                    explanation += (
                        f"Criteria {plateaued_str} have plateaued. "
                        "Spawn a novelty subagent in background \u2014 pass it the "
                        "plateaued_criteria detail from this result. It will propose "
                        "fundamentally different approaches to break through. "
                    )

            # Iteration-trigger mode: fire configured quality/novelty guidance
            # on round 2+ (not just when criteria plateau).
            elif failed_ids and (_spawn_quality or _spawn_novelty):
                if _spawn_quality and _spawn_novelty:
                    explanation += (
                        "Spawn a quality_rethinking subagent AND a novelty subagent "
                        "side-by-side in background \u2014 pass each the "
                        "failing_criteria_detail from this result (it contains "
                        "criterion text and category for every failing criterion). "
                        "Meanwhile, proceed with draft_approach and start "
                        "implementing. Integrate subagent proposals when they return. "
                    )
                elif _spawn_quality:
                    explanation += (
                        "Spawn a quality_rethinking subagent in background \u2014 pass "
                        "it the failing_criteria_detail from this result (it contains "
                        "criterion text and category for every failing criterion). "
                        "Meanwhile, proceed with draft_approach and start "
                        "implementing. Integrate subagent proposals when they return. "
                    )
                elif _spawn_novelty:
                    explanation += (
                        "Spawn a novelty subagent in background \u2014 pass it the "
                        "failing_criteria_detail from this result (it contains "
                        "criterion text and category for every failing criterion). "
                        "Meanwhile, proceed with draft_approach and start "
                        "implementing. Integrate subagent proposals when they return. "
                    )

            explanation += "NEXT STEP: Call `draft_approach` to plan what to build for each failing criterion. This is required before implementing."
        else:
            explanation = f"{true_count} of {len(items)} items passed (required: {required}). Verdict: {verdict}."

    # Apply diagnostic report gate (skip on first answer — nothing to diagnose yet).
    # Missing/invalid report is treated as a validation error: caller must fix and resubmit.
    report_gate_triggered = False
    if has_existing_answers and not report_eval.get("passed", True):
        report_gate_triggered = True
        report_issues = "; ".join(report_eval.get("issues", []))
        return _validation_error_payload(
            explanation=("Diagnostic report validation failed. " f"{report_issues} Fix the report and resubmit submit_checklist."),
            report_eval=report_eval,
            required=required,
            error_code="diagnostic_report_invalid",
            report_gate_triggered=True,
        )

    # Include report diagnostics for transparency on accepted submissions.
    if report_eval.get("provided"):
        report_summary = " Diagnostic report provided."
        if report_eval.get("issues"):
            report_summary += f" Report notes: {'; '.join(report_eval['issues'])}."
        explanation += report_summary

    # Reuse plateaued_failing from the iterate branch if computed, otherwise
    # compute fresh for the result dict (e.g. when report gate changed verdict).
    if not plateaued_failing and has_existing_answers and verdict != terminate_action:
        _item_cats = state.get("item_categories", {})
        _plateaued = _find_plateaued_criteria(
            items_detail,
            checklist_history or [],
            items=items,
            item_categories=_item_cats,
            min_rounds=2,
        )
        _failed_set = {d["id"] for d in items_detail if not d["passed"]}
        plateaued_failing = [d for d in _plateaued if d["id"] in _failed_set]

    result = {
        "status": "accepted",
        "verdict": verdict,
        "explanation": explanation,
        "true_count": true_count,
        "required": required,
        "items": items_detail,
        "failed_criteria": [d["id"] for d in items_detail if not d["passed"]],
        "plateaued_criteria": plateaued_failing,
        "report": report_eval,
        "report_gate_triggered": report_gate_triggered,
    }
    if best_agent is not None:
        result["best_agent"] = best_agent
    if per_agent_scores is not None:
        result["per_agent_scores"] = per_agent_scores

    # In iteration-trigger mode, include detail for ALL failing criteria so
    # agents can pass rich context to quality/novelty subagents on round 2+.
    _answer_count = state.get("agent_answer_count", 0)
    try:
        _answer_count = int(_answer_count)
    except (TypeError, ValueError):
        _answer_count = 0
    _iter_novelty_enabled = bool(state.get("enable_novelty_on_iteration")) and _answer_count >= 1
    _iter_quality_enabled = bool(state.get("enable_quality_rethink_on_iteration")) and _answer_count >= 1
    _spawn_novelty = bool(state.get("novelty_subagent_enabled", False)) and _iter_novelty_enabled
    _spawn_quality = bool(state.get("quality_rethinking_subagent_enabled", False)) and _iter_quality_enabled
    if (_spawn_novelty or _spawn_quality) and result.get("failed_criteria"):
        _item_cats = state.get("item_categories", {})
        failing_detail = []
        for d in items_detail:
            if not d["passed"]:
                idx = int(d["id"][1:]) - 1
                failing_detail.append(
                    {
                        "id": d["id"],
                        "text": items[idx] if idx < len(items) else d["id"],
                        "category": _item_cats.get(d["id"], "unknown"),
                        "current_score": d["score"],
                    },
                )
        result["failing_criteria_detail"] = failing_detail

    return result


def _convert_task_plan_to_inject_format(task_plan: list[dict]) -> list[dict]:
    """Convert task_plan items from evaluate_draft_approach to injection format.

    Args:
        task_plan: List of dicts in either legacy evaluator-task format
            ("explore"/"improve"/"verify_preserve") or already plan-compatible
            task specs ready for planning MCP consumption.

    Returns:
        List of dicts ready for inject_tasks.json consumption by planning MCP
    """
    tasks = []
    for item in task_plan:
        item_type = item.get("type")

        # Structured next_tasks payloads are already in planning-task format.
        # Pass them through while annotating metadata for injection provenance.
        if item_type not in {"explore", "improve", "novelty_quality_spawn", "verify_preserve"}:
            metadata = item.get("metadata")
            normalized_metadata = metadata.copy() if isinstance(metadata, dict) else {}
            normalized_item = item.copy()
            normalized_item["metadata"] = normalized_metadata
            normalized_execution = _normalize_task_execution_for_item(normalized_item)
            normalized_metadata["injected"] = True
            normalized_item["execution"] = normalized_execution
            normalized_metadata["execution"] = normalized_execution.copy()
            normalized_item.pop("subagent_name", None)
            normalized_item.pop("subagent_id", None)
            for key in (
                "verification",
                "verification_method",
                "impact",
                "relates_to",
                "sources",
                "chunk",
                "implementation_guidance",
                "success_criteria",
                "failure_signals",
                "required_evidence",
                "strategy_role",
            ):
                if key in normalized_item:
                    normalized_metadata.setdefault(key, normalized_item[key])
            tasks.append(normalized_item)
        elif item_type == "explore":
            explore_entry: dict = {
                "description": f"[OPPORTUNITY] {item['idea']}",
                "verification": item.get("rationale", ""),
                "priority": "high",
                "type": "explore",
                "impact": item.get("impact", "transformative"),
                "relates_to": item.get("relates_to", []),
                "metadata": {
                    "type": "explore",
                    "idea": item.get("idea", ""),
                    "rationale": item.get("rationale", ""),
                    "impact": item.get("impact", "transformative"),
                    "relates_to": item.get("relates_to", []),
                    "injected": True,
                },
            }
            normalized_execution = _normalize_task_execution_for_item(item)
            explore_entry["execution"] = normalized_execution
            explore_entry["metadata"]["execution"] = normalized_execution.copy()
            tasks.append(explore_entry)
        elif item_type == "improve":
            task = {
                "description": f"[{item['criterion_id']}] {item['plan']}",
                "verification": item["criterion"],
                "priority": "high",
                "type": "improve",
                "criterion_id": item["criterion_id"],
                "impact": item.get("impact", "incremental"),
                "sources": item.get("sources", []),
                "metadata": {
                    "criterion_id": item["criterion_id"],
                    "criterion": item["criterion"],
                    "type": "improve",
                    "impact": item.get("impact", "incremental"),
                    "sources": item.get("sources", []),
                    "injected": True,
                },
            }
            normalized_execution = _normalize_task_execution_for_item(item)
            task["execution"] = normalized_execution
            task["metadata"]["execution"] = normalized_execution.copy()
            tasks.append(task)
        elif item_type == "novelty_quality_spawn":
            metadata = {
                "type": "novelty_quality_spawn",
                "failing_criteria": item.get("metadata", {}).get("failing_criteria", []),
                "spawn_novelty": item.get("metadata", {}).get("spawn_novelty", True),
                "spawn_quality_rethinking": item.get("metadata", {}).get("spawn_quality_rethinking", True),
                "injected": True,
            }
            if "evaluation_input" in item.get("metadata", {}):
                metadata["evaluation_input"] = item.get("metadata", {}).get("evaluation_input")
            if "subagent_task_templates" in item.get("metadata", {}):
                metadata["subagent_task_templates"] = item.get("metadata", {}).get("subagent_task_templates")
            tasks.append(
                {
                    "id": item.get("id", "novelty_quality_spawn"),
                    "description": item["description"],
                    "verification": item.get(
                        "verification",
                        "Novelty/quality subagents spawned via spawn_subagents(background=True)",
                    ),
                    "verification_method": item.get(
                        "verification_method",
                        "list_subagents() shows spawned novelty/quality subagents",
                    ),
                    "priority": item.get("priority", "high"),
                    "type": "novelty_quality_spawn",
                    "execution": {"mode": "inline"},
                    "metadata": metadata,
                },
            )
        elif item_type == "verify_preserve":
            bullet_list = "; ".join(f"[{p['criterion_id']}] {p['what']} ({p['source']})" for p in item["items"])
            blind_eval_suffix = ""
            normalized_execution = _normalize_task_execution_for_item(item)
            if normalized_execution.get("subagent_type") in {"evaluator", "critic"}:
                blind_eval_suffix = " For anti-bias comparison, pass all candidate answers with neutral labels " "without revealing which answer is yours."
            task: dict[str, Any] = {
                "description": (
                    f"Before submitting: verify preserved strengths haven't regressed — {bullet_list}. "
                    "Confirm each preserved item is present in the actual output (run/render/screenshot, "
                    "not just checking the code), confirm preserved strengths remain intact, and make sure "
                    "earlier correctness fixes still pass after later changes. "
                    "Passing criteria scores also must not drop."
                    f"{blind_eval_suffix}"
                ),
                "verification": (
                    "All preserved elements verified in actual output (run/render/screenshot as appropriate), "
                    "not just present in source files; preserved strengths intact; earlier correctness fixes "
                    "still pass after later changes; passing criteria scores confirmed not dropped"
                ),
                "priority": "high",
                "metadata": {
                    "type": "verify_preserve",
                    "items": item["items"],
                    "injected": True,
                    "execution": normalized_execution.copy(),
                },
            }
            task["execution"] = normalized_execution
            tasks.append(task)
    return tasks


def _write_inject_file(injection_dir: Path | None, task_plan: list[dict]) -> None:
    """Write inject_tasks.json atomically to injection_dir for planning MCP consumption.

    Best-effort: silently skips on permission/OS errors. The draft_approach
    result is still returned to the agent in the tool response regardless, so the
    automatic task injection is a convenience, not a requirement. Suppressing errors
    here prevents agents from seeing filesystem errors and wasting rounds on workarounds.

    Args:
        injection_dir: Path to injection directory, or None (no-op)
        task_plan: Raw task_plan from evaluate_draft_approach
    """
    if injection_dir is None:
        return

    try:
        injection_dir = Path(injection_dir)
        injection_dir.mkdir(parents=True, exist_ok=True)
        tasks = _convert_task_plan_to_inject_format(task_plan)
        inject_file = injection_dir / "inject_tasks.json"
        tmp_file = injection_dir / "inject_tasks.json.tmp"

        tmp_file.write_text(json.dumps(tasks, indent=2))
        import os

        os.replace(str(tmp_file), str(inject_file))
    except (PermissionError, OSError):
        pass


def _register_checklist_tool(mcp: fastmcp.FastMCP, specs_path: Path, injection_dir: str | None = None) -> None:
    """Register the submit_checklist tool on the FastMCP server."""
    import inspect

    # Resolve injection dir for planning task injection
    _injection_dir_path: Path | None = Path(injection_dir) if injection_dir else None

    # Read specs once at startup just for the tool schema
    specs = _read_specs(specs_path)
    items = specs.get("items", [])
    schema_state = specs.get("state", {})
    schema_decomposition_mode = bool(schema_state.get("decomposition_mode", False))

    # Track last failed criteria so draft_approach can validate coverage
    _last_result: dict[str, Any] = {
        "status": "none",
        "verdict": None,
        "failed_criteria": [],
        "items": [],
        "all_criteria_ids": [],
        "failing_criteria_detail": [],
        "plateaued_criteria": [],
        "checklist_explanation": "",
        "diagnostic_report_path": "",
        "diagnostic_report_artifact_paths": [],
    }

    # Create handler that re-reads state on each call.
    async def submit_checklist(
        scores: dict,
        report_path: str = "",
        proposed_criteria: list = None,
    ) -> str:
        current = _read_specs(specs_path)
        current_items = current.get("items", items)
        state = current.get("state", {})
        # Bootstrap criteria emergence (Variant A) — accept proposed_criteria only
        # when criteria_mode == "bootstrap_inline". Persisted to a sibling JSONL
        # file the orchestrator drains in _drain_pending_criteria_proposals.
        if proposed_criteria and state.get("criteria_mode") == "bootstrap_inline":
            try:
                if isinstance(proposed_criteria, str):
                    try:
                        proposed_criteria = json.loads(proposed_criteria)
                    except (json.JSONDecodeError, TypeError):
                        proposed_criteria = None
                if isinstance(proposed_criteria, list):
                    out_path = Path(specs_path).parent / "proposed_criteria.jsonl"
                    with out_path.open("a", encoding="utf-8") as _f:
                        for entry in proposed_criteria:
                            if not isinstance(entry, dict):
                                continue
                            text = (entry.get("text") or "").strip()
                            if not text:
                                continue
                            _f.write(
                                json.dumps(
                                    {
                                        "text": text,
                                        "category": str(entry.get("category", "standard")).lower(),
                                        "anti_patterns": list(entry.get("anti_patterns") or []) or None,
                                    },
                                )
                                + "\n",
                            )
            except Exception:
                # Non-fatal: emission is a side-channel; don't block the checklist verdict.
                pass
        redirect_message = build_round_evaluator_task_mode_redirect(state)
        if redirect_message:
            return json.dumps({"error": redirect_message})

        # Codex sometimes sends scores as a JSON string; normalise to dict
        if isinstance(scores, str):
            try:
                scores = json.loads(scores)
            except (json.JSONDecodeError, TypeError):
                return json.dumps(
                    {"error": "scores must be a JSON object, not a string"},
                )
        if not isinstance(scores, dict):
            return json.dumps(
                {"error": "scores must be a JSON object"},
            )
        decomposition_mode = bool(state.get("decomposition_mode", False))
        item_prefix = str(state.get("item_prefix", "E"))
        submitted_agent_labels = _extract_submitted_agent_labels(scores, item_prefix=item_prefix)
        pending_recheck_labels = _normalize_pending_recheck_labels(state.get("pending_checklist_recheck_labels"))
        checklist_first_answer = bool(state.get("checklist_first_answer", False))
        max_calls = int(state.get("max_checklist_calls_per_round", 1) or 1)
        has_runtime_submit_state = any(
            key in state
            for key in (
                "agent_answer_count",
                "checklist_first_answer",
                "max_checklist_calls_per_round",
                "checklist_calls_this_round",
            )
        )
        try:
            raw_agent_answer_count = state.get("agent_answer_count", None)
            if raw_agent_answer_count is None:
                agent_answer_count = 1 if state.get("has_existing_answers", False) else 0
            else:
                agent_answer_count = int(raw_agent_answer_count or 0)
        except (TypeError, ValueError):
            agent_answer_count = 1 if state.get("has_existing_answers", False) else 0
        current_answer_label = str(state.get("current_answer_label") or "").strip()
        if agent_answer_count == 0 and current_answer_label and bool(state.get("has_existing_answers", False)):
            agent_answer_count = 1
        try:
            checklist_calls_this_round = int(state.get("checklist_calls_this_round", 0) or 0)
        except (TypeError, ValueError):
            checklist_calls_this_round = 0

        if raw_agent_answer_count is not None and not checklist_first_answer and agent_answer_count == 0:
            return json.dumps(
                {
                    "error": (
                        "submit_checklist is not available before your first answer is submitted. "
                        "Build your initial answer, verify it, then call the `new_answer` workflow tool. "
                        "Checklist evaluation begins from round 2."
                    ),
                },
            )

        state_for_eval = state
        using_recheck_exception = False
        if has_runtime_submit_state and checklist_calls_this_round >= max_calls:
            if not pending_recheck_labels:
                return json.dumps(
                    {
                        "error": (
                            f"submit_checklist already called {checklist_calls_this_round} time(s) "
                            f"this round (max: {max_calls}). You already have your improvement plan. "
                            "Implement those improvements, verify your changes, then call the "
                            "`new_answer` workflow tool to submit your completed work. "
                            "Do not call `submit_checklist` again."
                        ),
                    },
                )

            using_recheck_exception = True
            available_labels = set(state.get("available_agent_labels") or [])
            submitted_covers_full = decomposition_mode or (bool(submitted_agent_labels) and (not available_labels or available_labels.issubset(submitted_agent_labels)))
            submitted_covers_delta = decomposition_mode or (bool(submitted_agent_labels) and pending_recheck_labels.issubset(submitted_agent_labels))
            if submitted_covers_delta and not submitted_covers_full and not decomposition_mode:
                state_for_eval = dict(state)
                state_for_eval["available_agent_labels"] = sorted(pending_recheck_labels)

        result = evaluate_checklist_submission(
            scores=scores,
            report_path=report_path,
            items=current_items,
            state=state_for_eval,
            checklist_history=list(state.get("checklist_history") or []),
        )

        result_status = str(
            result.get("status", "accepted" if result.get("verdict") else "validation_error"),
        )
        iterate_action = state.get("iterate_action", "new_answer")
        if result_status == "accepted" and result.get("verdict") == iterate_action:
            result = dict(result)
            result["explanation"] = (
                result.get("explanation", "") + " NEXT: Call `draft_approach` to plan what to build for each failing criterion. " + "Then implement your plan and call `new_answer`."
            )

        report_data = result.get("report") if isinstance(result.get("report"), dict) else {}
        resolved_path = str(report_data.get("resolved_path") or "")
        fallback_path = str(report_data.get("path") or "")
        result_status = str(
            result.get("status", "accepted" if result.get("verdict") else "validation_error"),
        )
        submission_has_validation_error = bool(
            (result_status != "accepted") or result.get("error") or result.get("incomplete_scores") or result.get("report_gate_triggered"),
        )

        if not submission_has_validation_error:
            history = list(state.get("checklist_history") or [])
            history.append(
                {
                    "verdict": result.get("verdict"),
                    "true_count": result.get("true_count"),
                    "total_score": sum(d["score"] for d in result.get("items", [])),
                    "items_detail": result.get("items", []),
                },
            )
            state["checklist_history"] = history
            state["checklist_calls_this_round"] = checklist_calls_this_round + 1
            submitted_covers_full = False
            submitted_covers_delta = False
            if decomposition_mode:
                submitted_covers_full = True
                submitted_covers_delta = True
            elif pending_recheck_labels and submitted_agent_labels:
                available_labels = set(state.get("available_agent_labels") or [])
                submitted_covers_full = bool(available_labels) and available_labels.issubset(submitted_agent_labels)
                submitted_covers_delta = pending_recheck_labels.issubset(submitted_agent_labels)
            if pending_recheck_labels and ((submitted_agent_labels and (submitted_covers_delta or submitted_covers_full)) or (using_recheck_exception and decomposition_mode)):
                state["pending_checklist_recheck_labels"] = []
            try:
                write_checklist_specs(current_items, state, specs_path)
            except Exception as exc:
                logger.warning(f"Failed to persist checklist runtime state: {exc}")

        _last_result["status"] = str(
            result.get("status", "accepted" if result.get("verdict") else "validation_error"),
        )
        _last_result["verdict"] = result.get("verdict")
        _last_result["failed_criteria"] = result.get("failed_criteria", [])
        _last_result["items"] = current_items
        _last_result["all_criteria_ids"] = [f"E{i+1}" for i in range(len(current_items))]
        _last_result["failing_criteria_detail"] = list(result.get("failing_criteria_detail", []))
        _last_result["plateaued_criteria"] = list(result.get("plateaued_criteria", []))
        _last_result["checklist_explanation"] = str(result.get("explanation", ""))
        _last_result["diagnostic_report_path"] = resolved_path or fallback_path
        _last_result["diagnostic_report_artifact_paths"] = list(report_data.get("artifact_paths", []))
        return json.dumps(result)

    if schema_decomposition_mode:
        submit_checklist.__doc__ = (
            "Submit your checklist evaluation for your current subtask output. "
            "Use flat scores in 'scores' with criterion keys like "
            '{"E1": {"score": 8, "reasoning": "..."}, "E2": {...}}. '
            "If peer work changed your integration points, re-evaluate your current work "
            "against the latest context before deciding whether to stop or iterate. "
            "Use 'report_path' to provide a markdown gap report when report gating is enabled."
        )
    else:
        submit_checklist.__doc__ = (
            "Submit your checklist evaluation. "
            "Score each agent's answer separately per criterion, then submit all "
            "agent scores in 'scores' as a nested object: "
            '{"agent1.1": {"E1": {"score": 8, "reasoning": "..."}, ...}, "agent2.1": {...}}. '
            "Use the exact agent labels from the <CURRENT ANSWERS> headers in your context "
            "(labels follow the format agentX.Y — use the full label including the .Y suffix). "
            "The verdict is determined by the strongest agent's scores — the agent "
            "with the highest aggregate across all criteria. Include all agents so "
            "the evaluation is transparent and auditable. "
            "Use 'report_path' to provide a markdown gap report when report gating "
            "is enabled."
        )

    # Set proper signature so FastMCP sees all parameters
    _params = [
        inspect.Parameter("scores", inspect.Parameter.POSITIONAL_OR_KEYWORD),
        inspect.Parameter("report_path", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=""),
    ]
    if schema_state.get("criteria_mode") == "bootstrap_inline":
        _params.append(
            inspect.Parameter("proposed_criteria", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None),
        )
        # Also surface the new field in the tool description so the model
        # bridges "the prompt asks me to emit X" with "this tool has a
        # parameter X". Without this hint, schemas alone aren't enough — the
        # model often submits scores + report_path and skips the new field.
        submit_checklist.__doc__ = (submit_checklist.__doc__ or "") + (
            " ALSO emit 'proposed_criteria': a short list (<=3) of criterion "
            'objects {"text": "...", "category": "primary|standard|stretch", '
            '"anti_patterns": ["..."]} describing quality dimensions a stronger '
            "answer would satisfy that the current answers do NOT. These flow "
            "into subsequent rounds' checklist. Skip only when no genuine gap "
            "is visible — at most one round in three should skip entirely."
        )
    sig = inspect.Signature(_params)
    submit_checklist.__signature__ = sig

    mcp.tool(
        name="submit_checklist",
        description=submit_checklist.__doc__,
    )(submit_checklist)

    # draft_approach: validate improvement coverage for all failing criteria
    async def draft_approach(improvements: dict, preserve: dict = None, vision: str = None) -> str:
        if isinstance(improvements, str):
            try:
                improvements = json.loads(improvements)
            except (json.JSONDecodeError, TypeError):
                return json.dumps(
                    {"valid": False, "error": "improvements must be a JSON object"},
                )
        if isinstance(preserve, str):
            try:
                preserve = json.loads(preserve)
            except (json.JSONDecodeError, TypeError):
                preserve = None

        current_for_improve = _read_specs(specs_path)
        state_for_improve = current_for_improve.get("state", {})
        redirect_message = build_round_evaluator_task_mode_redirect(state_for_improve)
        if redirect_message:
            return json.dumps({"valid": False, "error": redirect_message})
        iterate_action = state_for_improve.get("iterate_action", "new_answer")
        status = str(_last_result.get("status", "none"))
        verdict = _last_result.get("verdict")
        if status != "accepted":
            return json.dumps(
                {
                    "valid": False,
                    "error": ("draft_approach is unavailable because your latest submit_checklist " "result was a validation error. Fix and resubmit submit_checklist first."),
                },
            )
        if verdict != iterate_action:
            return json.dumps(
                {
                    "valid": False,
                    "error": ("draft_approach is only available after submit_checklist returns " f"an iterate verdict ({iterate_action})."),
                },
            )
        pending_recheck_labels = _normalize_pending_recheck_labels(state_for_improve.get("pending_checklist_recheck_labels"))
        if pending_recheck_labels:
            pending_labels_text = ", ".join(sorted(pending_recheck_labels))
            return json.dumps(
                {
                    "valid": False,
                    "error": (
                        "draft_approach is unavailable because newer injected answer labels "
                        f"still require checklist re-evaluation: {pending_labels_text}. "
                        "Re-run submit_checklist on the newest labels first."
                    ),
                },
            )
        result = evaluate_draft_approach(
            improvements=improvements,
            failed_criteria=_last_result["failed_criteria"],
            items=_last_result["items"],
            all_criteria_ids=_last_result.get("all_criteria_ids"),
            preserve=preserve,
            state=state_for_improve,
            latest_evaluation={
                "failed_criteria": _last_result.get("failed_criteria", []),
                "failing_criteria_detail": _last_result.get("failing_criteria_detail", []),
                "plateaued_criteria": _last_result.get("plateaued_criteria", []),
                "checklist_explanation": _last_result.get("checklist_explanation", ""),
                "diagnostic_report_path": _last_result.get("diagnostic_report_path", ""),
                "diagnostic_report_artifact_paths": _last_result.get("diagnostic_report_artifact_paths", []),
            },
            vision=vision,
        )
        if result.get("valid") and _injection_dir_path:
            _write_inject_file(_injection_dir_path, result["task_plan"])
            task_count = len(result["task_plan"])
            result = dict(result)  # Don't mutate original
            result["message"] = (
                f"Your task plan has been pre-populated with {task_count} items. "
                "Call get_task_plan to see the list and start executing. "
                "Correctness-critical tasks come first; if explicit correctness "
                "criteria exist, use them as anchors. Preserve items are the "
                "final regression check — verify after implementing that "
                "preserved strengths remain and earlier correctness fixes still "
                "hold. Do not defer blocker correctness fixes in favor of "
                "easier polish."
            )
            # Append subagent delegation guidance when subagents are enabled
            if state_for_improve.get("subagents_enabled"):
                builder_criteria_ids: list[str] = []
                for task in result["task_plan"]:
                    execution = task.get("execution") or {}
                    if task.get("type") == "improve" and execution.get("mode") == "delegate" and execution.get("subagent_type") == "builder":
                        cid = task.get("criterion_id")
                        if cid and cid not in builder_criteria_ids:
                            builder_criteria_ids.append(cid)
                if builder_criteria_ids:
                    result["message"] += " Builder-suggested criteria: " + ", ".join(builder_criteria_ids) + "."
                has_novelty_spawn = bool(result["task_plan"]) and result["task_plan"][0].get("type") == "novelty_quality_spawn"
                if has_novelty_spawn:
                    result["message"] += " A novelty/quality spawn task is first in your plan —" " spawn it in background before implementing improvements."
                result["message"] += (
                    " Spawn one builder per task — do NOT bundle multiple E{x}" " into a single builder spec. Each builder task is" " independent — spawn all in a single spawn_subagents()" " call."
                )
        return json.dumps(result)

    draft_approach.__doc__ = (
        "Propose what to build for your next answer. "
        "Must be called after submit_checklist returns an iterate verdict. "
        "Pass 'improvements' mapping criterion IDs (e.g. 'E2') to lists of "
        "entries, each with 'plan' (what to do) and 'sources' (which answers "
        "to draw from, or 'fresh' for new ideas). Optionally pass 'vision' "
        "for a north-star description of the ideal output. Pass 'preserve' "
        "mapping criterion IDs to entries with 'what' (strength to protect) "
        "and 'source' (which answer)."
    )

    propose_sig = inspect.Signature(
        [
            inspect.Parameter("improvements", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter("preserve", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None),
            inspect.Parameter("vision", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None),
        ],
    )
    draft_approach.__signature__ = propose_sig

    mcp.tool(
        name="draft_approach",
        description=draft_approach.__doc__,
    )(draft_approach)

    # --- set_evaluator_personas tool ---
    # Always register; gate on enable_evaluator_personas at call time (re-reads
    # specs) because for Codex the specs file may not exist yet at server startup.
    async def set_evaluator_personas(personas: list) -> str:
        current = _read_specs(specs_path)
        state = current.get("state", {})

        if not bool(state.get("enable_evaluator_personas", False)):
            return json.dumps({"error": "set_evaluator_personas is not enabled in this configuration"})

        team_size = int(state.get("evaluator_team_size", 0) or 0)

        # Codex sometimes sends JSON strings; normalise
        if isinstance(personas, str):
            try:
                personas = json.loads(personas)
            except (json.JSONDecodeError, TypeError):
                return json.dumps({"error": "personas must be a JSON array"})
        if not isinstance(personas, list):
            return json.dumps({"error": "personas must be a JSON array"})

        if team_size > 0 and len(personas) != team_size:
            return json.dumps(
                {
                    "error": f"Expected {team_size} persona(s) to match evaluator team size, got {len(personas)}",
                },
            )
        for i, p in enumerate(personas):
            if not isinstance(p, dict):
                return json.dumps({"error": f"Persona at index {i} must be an object"})
            if not str(p.get("label", "")).strip():
                return json.dumps({"error": f"Persona at index {i} has empty label"})
            if not str(p.get("instructions", "")).strip():
                return json.dumps({"error": f"Persona at index {i} has empty instructions"})

        # Write back to specs so orchestrator can read
        state["pending_evaluator_personas"] = [{"label": str(p["label"]).strip(), "instructions": str(p["instructions"]).strip()} for p in personas]
        current["state"] = state
        try:
            with open(specs_path, "w") as f:
                json.dump(current, f, indent=2, default=str)
        except Exception as exc:
            return json.dumps({"error": f"Failed to write personas: {exc}"})

        labels = [p["label"] for p in state["pending_evaluator_personas"]]
        return json.dumps(
            {
                "status": "accepted",
                "message": f"Evaluator personas set: {', '.join(labels)}. " "These will be applied to the next round evaluator run.",
            },
        )

    set_evaluator_personas.__doc__ = (
        "Configure distinct evaluation lenses for round evaluator subagents. "
        "Call before new_answer to shape how evaluators critique your next submission. "
        "Each persona needs 'label' (short name) and 'instructions' (critique focus). "
        "Count must match evaluator team size."
    )
    set_personas_sig = inspect.Signature(
        [inspect.Parameter("personas", inspect.Parameter.POSITIONAL_OR_KEYWORD)],
    )
    set_evaluator_personas.__signature__ = set_personas_sig

    mcp.tool(
        name="set_evaluator_personas",
        description=set_evaluator_personas.__doc__,
    )(set_evaluator_personas)

    logger.info("Registered submit_checklist + draft_approach + set_evaluator_personas MCP tools")


# ---------- spec file I/O ----------


def write_checklist_specs(
    items: list,
    state: dict[str, Any],
    output_path: Path,
) -> Path:
    """Write checklist specs + state to a JSON file.

    Called by the orchestrator before launch and whenever state changes.
    """
    specs = {
        "items": items,
        "state": state,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        # State may include pathlib objects (for example workspace paths)
        # that need string normalization for JSON transport.
        json.dump(specs, f, indent=2, default=str)
    return output_path


def build_server_config(
    specs_path: Path,
    hook_dir: Path | None = None,
) -> dict[str, Any]:
    """Build a stdio MCP server config dict for the checklist server."""
    script_path = Path(__file__).resolve()

    cmd_args = [
        "run",
        f"{script_path}:create_server",
        "--",
        "--specs",
        str(specs_path),
    ]
    if hook_dir is not None:
        cmd_args.extend(["--hook-dir", str(hook_dir)])

    return {
        "name": SERVER_NAME,
        "type": "stdio",
        "command": "fastmcp",
        "args": cmd_args,
        "env": {"FASTMCP_SHOW_CLI_BANNER": "false"},
        "tool_timeout_sec": 120,
    }
