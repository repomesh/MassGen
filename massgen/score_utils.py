"""Canonical helpers for reading checklist/criterion score payloads.

Checklist scores arrive in two shapes that several modules need to parse:

  - flat:      {"E1": {"score": 8, "reasoning": "..."}, "E2": 5, ...}
  - per-agent: {"agent1.1": {"E1": {...}, ...}, "agent2.1": {...}}

Score values may be a plain number or a ``{"score": N, "reasoning": str}`` dict.
This module is the single source of truth for extracting a numeric score and for
detecting the per-agent shape, replacing previously duplicated copies in
``mcp_tools/checklist_tools_server.py``, ``mcp_tools/standalone/quality_server.py``,
and ``bootstrap_criteria.py``.
"""

from __future__ import annotations

from typing import Any


def extract_score(entry: Any, *, default: Any = 0) -> Any:
    """Return the numeric score from a raw entry, else ``default``.

    Accepts a plain number or a ``{"score": N}`` dict. Returns ``default`` when no
    usable numeric score is present (missing key, ``None``, non-numeric, or ``bool``
    — which is an ``int`` subclass and must not be treated as a score). The numeric
    type is preserved (an ``int`` stays an ``int``).

    Pass ``default=None`` to distinguish "no score" from a real 0 (used by callers
    that filter out unscored entries).
    """
    value = entry.get("score") if isinstance(entry, dict) else entry
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return value
    return default


def is_per_agent_scores(scores: dict[str, Any], item_prefix: str = "E") -> bool:
    """Return True when ``scores`` is the per-agent shape (keyed by agent label).

    Flat submissions are keyed by criterion id (``item_prefix``/``E``/``T``-prefixed);
    per-agent submissions are keyed by agent labels like ``agent1.1``. Empty input is
    treated as flat (not per-agent).
    """
    if not scores:
        return False
    return not any(k.startswith(item_prefix) or k.startswith("T") or k.startswith("E") for k in scores)
