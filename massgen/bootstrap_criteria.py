"""Discriminative criteria emergence (bootstrap_criteria).

Pure helpers for the v0.1.85 feature where agents emit criteria a stronger
answer would satisfy that the current answers do not. The orchestrator owns
an accumulator across rounds; this module provides the merge logic in a
testable, side-effect-free form.

The schema for a proposal dict mirrors ``GeneratedCriterion`` / inline criteria
(see ``massgen/evaluation_criteria_generator.py``):

    {
        "text": str,                 # required, non-empty after strip
        "category": str,             # one of "primary" | "standard" | "stretch"
        "anti_patterns": list[str],  # optional
        "verify_by": str,            # optional
    }

Only ``text`` is enforced here. Category/anti_pattern normalization happens
downstream in ``criteria_from_inline``.
"""

from __future__ import annotations

from typing import Any


def merge_proposals(
    accumulator: list[dict[str, Any]],
    new_proposals: list[dict[str, Any]],
    *,
    cap: int,
) -> list[dict[str, Any]]:
    """Merge new criteria proposals into the accumulator.

    Semantics (kept deliberately simple for v1 per CLAUDE.md anti-patterns:
    no Jaccard / keyword similarity heuristics):

    - Dedupes by exact stripped ``text`` match across both the existing
      accumulator and the new proposals.
    - Skips entries missing a usable ``text`` value or whose text is whitespace.
    - Enforces ``cap`` via FIFO eviction (oldest entries dropped first) once
      ``cap > 0`` is exceeded. ``cap == 0`` means unlimited.
    """
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for entry in accumulator:
        text = (entry.get("text") or "").strip()
        if not text or text in seen:
            continue
        merged.append({**entry, "text": text})
        seen.add(text)

    for proposal in new_proposals:
        text = (proposal.get("text") or "").strip()
        if not text or text in seen:
            continue
        merged.append({**proposal, "text": text})
        seen.add(text)

    if cap > 0 and len(merged) > cap:
        merged = merged[-cap:]
    return merged


def augment_with_accumulator(
    base_items: list[str],
    base_categories: dict[str, str],
    base_verify_by: dict[str, str] | None,
    base_anti_patterns: dict[str, list[str]] | None,
    base_score_anchors: dict[str, dict[str, str]] | None,
    accumulator: list[dict[str, Any]],
) -> tuple[
    list[str],
    dict[str, str],
    dict[str, str] | None,
    dict[str, list[str]] | None,
    dict[str, dict[str, str]] | None,
]:
    """Append accumulator entries to a base criteria set.

    Continues ID numbering ``E{N+1}, E{N+2}, ...`` after the base items.
    Skips duplicate texts (exact match against base items and prior accumulator
    entries already added). Returns mutable copies so callers don't share state
    with the orchestrator's accumulator list.
    """
    items = list(base_items)
    categories = dict(base_categories)
    verify_by: dict[str, str] = dict(base_verify_by or {})
    anti: dict[str, list[str]] = dict(base_anti_patterns or {})
    anchors: dict[str, dict[str, str]] = dict(base_score_anchors or {})

    seen_texts = {t.strip() for t in items if t}
    next_idx = len(items) + 1
    for entry in accumulator:
        text = (entry.get("text") or "").strip()
        if not text or text in seen_texts:
            continue
        ident = f"E{next_idx}"
        items.append(text)
        seen_texts.add(text)
        raw_cat = str(entry.get("category", "standard")).strip().lower()
        if raw_cat in ("must", "core", "standard"):
            cat = "standard"
        elif raw_cat == "primary":
            cat = "primary"
        elif raw_cat in ("could", "stretch"):
            cat = "stretch"
        else:
            cat = "standard"
        categories[ident] = cat
        raw_anti = entry.get("anti_patterns")
        if isinstance(raw_anti, list):
            anti[ident] = list(raw_anti)
        verify = (entry.get("verify_by") or "").strip()
        if verify:
            verify_by[ident] = verify
        next_idx += 1

    return (
        items,
        categories,
        verify_by or None,
        anti or None,
        anchors or None,
    )


_VALID_CRITERIA_MODES = frozenset({"static", "bootstrap_inline", "bootstrap_subagent"})


def is_bootstrap_mode(criteria_mode: str | None) -> bool:
    """Return True when ``criteria_mode`` is a bootstrap variant."""
    return criteria_mode in {"bootstrap_inline", "bootstrap_subagent"}


def validate_criteria_mode(criteria_mode: str) -> None:
    """Raise ``ValueError`` if ``criteria_mode`` is not a recognized value."""
    if criteria_mode not in _VALID_CRITERIA_MODES:
        raise ValueError(
            f"Invalid criteria_mode: '{criteria_mode}'. " f"Must be one of: {sorted(_VALID_CRITERIA_MODES)}",
        )
