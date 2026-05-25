"""Standalone MCP server exposing MassGen quality tools.

Tools: generate_eval_criteria (storage), submit_checklist, draft_approach,
reset_evaluation.

State is stored per-session in `.massgen-quality/sessions/{session_id}/`.
The session_id is read from `.massgen-quality/session_metadata.json` (written
by the massgen-refinery SessionStart hook). If no session metadata exists,
falls back to a `default` session directory.

Usage:
    python -m massgen.mcp_tools.standalone.quality_server
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fastmcp

from massgen.score_utils import extract_score

logger = logging.getLogger(__name__)

SERVER_NAME = "massgen_quality_tools"
QUALITY_DIR = ".massgen-quality"
DEFAULT_CUTOFF = 7  # Score threshold (0-10) for passing a criterion
DEFAULT_REQUIRED_RATIO = 1.0  # Fraction of criteria that must pass

mcp = fastmcp.FastMCP(SERVER_NAME)


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def _safe_session_id(raw: str) -> str:
    """Return a filesystem-safe slug for use as a session directory name."""
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", raw).strip("_")
    return slug if slug and slug not in (".", "..") else "default"


def _get_session_dir() -> Path:
    """Resolve the current session directory from session_metadata.json."""
    quality_root = Path.cwd() / QUALITY_DIR
    metadata_path = quality_root / "session_metadata.json"

    session_id = "default"
    if metadata_path.exists():
        try:
            with open(metadata_path) as f:
                metadata = json.load(f)
            session_id = _safe_session_id(metadata.get("session_id", "default"))
        except (json.JSONDecodeError, OSError):
            pass

    session_dir = quality_root / "sessions" / session_id
    # Validate the resolved path stays within the sessions root
    sessions_root = (quality_root / "sessions").resolve()
    if not session_dir.resolve().is_relative_to(sessions_root):
        session_dir = quality_root / "sessions" / "default"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _read_criteria(session_dir: Path) -> list[dict[str, Any]]:
    """Read stored criteria from session directory."""
    criteria_path = session_dir / "criteria.json"
    if not criteria_path.exists():
        return []
    try:
        with open(criteria_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _read_state(session_dir: Path) -> dict[str, Any]:
    """Read evaluation state from session directory."""
    state_path = session_dir / "state.json"
    if not state_path.exists():
        return {"checklist_history": [], "last_result": None, "round": 0}
    try:
        with open(state_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"checklist_history": [], "last_result": None, "round": 0}


def _write_state(session_dir: Path, state: dict[str, Any]) -> None:
    """Write evaluation state to session directory."""
    state_path = session_dir / "state.json"
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def _extract_score(entry: Any) -> int:
    """Extract numeric score (int) from int or {"score": int, "reasoning": str}."""
    return int(extract_score(entry))


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


async def _init_session_impl(
    label: str = "",
) -> str:
    """Create a new timestamped session directory (core logic)."""
    quality_root = Path.cwd() / QUALITY_DIR
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_label = _safe_session_id(label) if label else ""
    session_id = f"{timestamp}_{safe_label}" if safe_label else timestamp

    session_dir = quality_root / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # Write session_metadata.json so all tools use this session
    metadata_path = quality_root / "session_metadata.json"
    quality_root.mkdir(parents=True, exist_ok=True)
    with open(metadata_path, "w") as f:
        json.dump(
            {
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "label": label,
            },
            f,
            indent=2,
        )

    return json.dumps(
        {
            "status": "ok",
            "session_id": session_id,
            "session_dir": str(session_dir),
        },
    )


async def _generate_eval_criteria_impl(
    criteria: list[dict[str, str]],
) -> str:
    """Store evaluation criteria for the current session (core logic)."""
    if not isinstance(criteria, list) or not criteria:
        return json.dumps(
            {
                "status": "error",
                "error": "criteria must be a non-empty list of {id, text} objects",
            },
        )

    # Validate each criterion has at least id and text
    validated = []
    for c in criteria:
        if not isinstance(c, dict) or "id" not in c or "text" not in c:
            return json.dumps(
                {
                    "status": "error",
                    "error": f"Each criterion must have 'id' and 'text'. Got: {c}",
                },
            )
        validated.append(
            {
                "id": str(c["id"]),
                "text": str(c["text"]),
                "category": str(c.get("category", "standard")),
                "rationale": str(c.get("rationale", "")),
            },
        )

    session_dir = _get_session_dir()
    criteria_path = session_dir / "criteria.json"
    with open(criteria_path, "w") as f:
        json.dump(validated, f, indent=2)

    return json.dumps(
        {
            "status": "ok",
            "criteria_count": len(validated),
            "path": str(criteria_path),
        },
    )


async def _submit_checklist_impl(
    scores: dict[str, Any],
    report_path: str = "",
) -> str:
    """Evaluate checklist submission and return verdict (core logic)."""
    session_dir = _get_session_dir()
    criteria = _read_criteria(session_dir)

    if not criteria:
        return json.dumps(
            {
                "status": "error",
                "error": ("No criteria registered. Call generate_eval_criteria first " "to store evaluation criteria for this session."),
            },
        )

    if not isinstance(scores, dict):
        return json.dumps(
            {
                "status": "error",
                "error": "scores must be a dict mapping criterion IDs to scores",
            },
        )

    state = _read_state(session_dir)
    checklist_history = state.get("checklist_history", [])
    round_num = state.get("round", 0) + 1

    # Evaluate each criterion
    items_detail = []
    for criterion in criteria:
        cid = criterion["id"]
        entry = scores.get(cid)
        if entry is None:
            return json.dumps(
                {
                    "status": "error",
                    "error": f"Missing score for criterion {cid}. All criteria must be scored.",
                    "criteria_ids": [c["id"] for c in criteria],
                },
            )
        score = _extract_score(entry)
        passed = score >= DEFAULT_CUTOFF
        reasoning = ""
        if isinstance(entry, dict):
            reasoning = str(entry.get("reasoning", ""))
        items_detail.append(
            {
                "id": cid,
                "text": criterion["text"],
                "score": score,
                "passed": passed,
                "reasoning": reasoning,
            },
        )

    # Compute verdict
    required = len(criteria)
    true_count = sum(1 for d in items_detail if d["passed"])
    failed = [d for d in items_detail if not d["passed"]]
    failed_ids = [d["id"] for d in failed]

    if true_count >= required:
        verdict = "converge"
        explanation = f"All {len(criteria)} criteria passed (scores >= {DEFAULT_CUTOFF}). " f"Quality bar met. Verdict: converge."
    else:
        verdict = "iterate"
        explanation = f"{true_count} of {len(criteria)} criteria passed " f"(required: {required}). " f"Verdict: iterate. " f"Criteria needing improvement: {', '.join(failed_ids)}."

        # Detect plateaued criteria
        if len(checklist_history) >= 2:
            plateaued = _find_plateaued(items_detail, checklist_history)
            if plateaued:
                plateau_str = ", ".join(f"{p['id']} (scores: {' -> '.join(str(s) for s in p['score_history'])})" for p in plateaued)
                explanation += f" Plateaued criteria: {plateau_str}. " "Consider a different approach for these."

        explanation += " NEXT STEP: Call draft_approach with specific " "improvements for each failing criterion."

    # Build result
    result = {
        "status": "accepted",
        "verdict": verdict,
        "round": round_num,
        "explanation": explanation,
        "items": items_detail,
        "failed_criteria": failed_ids,
        "failing_criteria_detail": [{"id": d["id"], "text": d["text"], "score": d["score"]} for d in failed],
    }

    # Update state
    checklist_history.append(
        {
            "round": round_num,
            "items_detail": items_detail,
            "verdict": verdict,
        },
    )
    state["checklist_history"] = checklist_history
    state["last_result"] = result
    state["round"] = round_num
    _write_state(session_dir, state)

    return json.dumps(result)


def _find_plateaued(
    current_items: list[dict],
    history: list[dict],
    min_rounds: int = 2,
) -> list[dict]:
    """Find criteria whose scores haven't improved across recent rounds."""
    if len(history) < min_rounds:
        return []

    current_by_id = {d["id"]: d["score"] for d in current_items}
    plateaued = []

    for cid, current_score in current_by_id.items():
        stuck = True
        score_history = []
        for entry in history[-min_rounds:]:
            prev_items = {d["id"]: d["score"] for d in entry.get("items_detail", [])}
            prev_score = prev_items.get(cid)
            score_history.append(prev_score)
            if prev_score is None or current_score > prev_score + 1:
                stuck = False
                break
        if stuck:
            score_history.append(current_score)
            plateaued.append(
                {
                    "id": cid,
                    "score_history": score_history,
                    "current_score": current_score,
                },
            )

    return plateaued


async def _draft_approach_impl(
    improvements: dict[str, Any],
    preserve: dict[str, Any] | None = None,
    vision: str | None = None,
) -> str:
    """Validate improvement coverage against last checklist result (core logic)."""
    session_dir = _get_session_dir()
    state = _read_state(session_dir)
    last_result = state.get("last_result")

    if not last_result:
        return json.dumps(
            {
                "status": "error",
                "error": "No prior submit_checklist result. Call submit_checklist first.",
            },
        )

    if last_result.get("verdict") != "iterate":
        return json.dumps(
            {
                "status": "error",
                "error": "draft_approach is only available after an iterate verdict.",
            },
        )

    if not isinstance(improvements, dict):
        return json.dumps(
            {
                "status": "error",
                "error": "improvements must be a dict mapping criterion IDs to lists",
            },
        )

    failed_criteria = last_result.get("failed_criteria", [])
    if not failed_criteria:
        return json.dumps(
            {
                "status": "error",
                "error": "No failed criteria to improve.",
            },
        )

    # Check coverage
    missing = [cid for cid in failed_criteria if cid not in improvements]
    empty = [cid for cid in failed_criteria if cid in improvements and not improvements[cid]]

    if missing or empty:
        issues = []
        if missing:
            issues.append(f"Missing improvements for: {', '.join(missing)}")
        if empty:
            issues.append(f"Empty improvements for: {', '.join(empty)}")
        return json.dumps(
            {
                "status": "error",
                "valid": False,
                "error": "; ".join(issues),
                "missing_criteria": missing,
                "empty_criteria": empty,
                "failed_criteria": failed_criteria,
            },
        )

    # Check impact gate: at least one non-incremental improvement
    all_entries = []
    for entries in improvements.values():
        if isinstance(entries, list):
            all_entries.extend(entries)
        else:
            all_entries.append(entries)

    non_incremental = sum(1 for e in all_entries if isinstance(e, dict) and e.get("impact") in ("transformative", "structural"))

    if non_incremental == 0:
        return json.dumps(
            {
                "status": "error",
                "valid": False,
                "error": ("All improvements are incremental. At least one must be " "structural or transformative. Consider a different approach " "for the weakest criteria."),
            },
        )

    return json.dumps(
        {
            "status": "accepted",
            "valid": True,
            "message": (f"Improvements validated for {len(failed_criteria)} criteria. " f"{non_incremental} non-incremental change(s). " "Proceed with implementation."),
            "improvements_count": len(all_entries),
            "non_incremental_count": non_incremental,
        },
    )


async def _reset_evaluation_impl() -> str:
    """Reset evaluation state for a fresh round (core logic)."""
    session_dir = _get_session_dir()
    state_path = session_dir / "state.json"

    fresh_state = {"checklist_history": [], "last_result": None, "round": 0}
    with open(state_path, "w") as f:
        json.dump(fresh_state, f, indent=2)

    return json.dumps(
        {
            "status": "ok",
            "message": "Evaluation state reset. Criteria preserved.",
        },
    )


# ---------------------------------------------------------------------------
# MCP tool registrations (delegate to _impl functions for testability)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="init_session",
    description=(
        "Initialize a new evaluation session with a timestamped directory. "
        "Call this at the start of each /refine invocation to create isolated "
        "state for the session. Optional label for identification."
    ),
)
async def init_session(label: str = "") -> str:
    return await _init_session_impl(label)


@mcp.tool(
    name="generate_eval_criteria",
    description=(
        "Store evaluation criteria for the current session. The agent generates "
        "criteria itself, then calls this tool to register them so that "
        "submit_checklist and draft_approach can reference them. "
        "Input: a list of criteria objects with id, text, and optional category."
    ),
)
async def generate_eval_criteria(criteria: list[dict[str, str]]) -> str:
    return await _generate_eval_criteria_impl(criteria)


@mcp.tool(
    name="submit_checklist",
    description=(
        "Evaluate work against stored criteria. Submit scores for each "
        "criterion (E1, E2, etc.) as integers 0-10 or as "
        '{"score": N, "reasoning": "..."}. Returns a verdict: '
        '"iterate" (keep improving) or "converge" (quality bar met). '
        "Must call generate_eval_criteria first to register criteria."
    ),
)
async def submit_checklist(scores: dict[str, Any], report_path: str = "") -> str:
    return await _submit_checklist_impl(scores, report_path)


@mcp.tool(
    name="draft_approach",
    description=(
        "Propose what to build for your next answer. "
        "Call after submit_checklist returns an iterate verdict. "
        "Input: a dict mapping criterion IDs to lists of entries. "
        "Each entry should have 'plan' (str) and optional 'impact' "
        "(transformative/structural/incremental)."
    ),
)
async def draft_approach(
    improvements: dict[str, Any],
    preserve: dict[str, Any] | None = None,
    vision: str | None = None,
) -> str:
    return await _draft_approach_impl(improvements, preserve, vision=vision)


@mcp.tool(
    name="reset_evaluation",
    description=("Reset evaluation state for a fresh round. Clears checklist history " "and last verdict. Criteria are preserved unless new criteria are " "registered via generate_eval_criteria."),
)
async def reset_evaluation() -> str:
    return await _reset_evaluation_impl()


if __name__ == "__main__":
    mcp.run()
