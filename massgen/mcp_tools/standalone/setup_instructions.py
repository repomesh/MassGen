"""Inject checkpoint instructions into a project's CLAUDE.md (or AGENTS.md).

Managed-block approach: the script wraps the instructions between marker
comments so re-running updates the content idempotently.

Usage:
    massgen-checkpoint-setup                      # patches ./CLAUDE.md
    massgen-checkpoint-setup --target ./AGENTS.md # patches a different file
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

MARKER_START = "<!-- MASSGEN-CHECKPOINT:START -->"
MARKER_END = "<!-- MASSGEN-CHECKPOINT:END -->"

# Inline markers delimiting the recheckpoint-triggers section in the
# canonical instructions file. `load_template(single_checkpoint=True)`
# drops everything between (and including) these markers so the executor
# never sees the recheckpoint affordance in single-shot mode. Keeping it
# as one source file avoids drift between a single/multi pair.
RECHECKPOINT_MARKER_START = "<!-- RECHECKPOINT-SECTION:START -->"
RECHECKPOINT_MARKER_END = "<!-- RECHECKPOINT-SECTION:END -->"

_TEMPLATE_PATH = Path(__file__).parent / "checkpoint_instructions.md"

# Regex that matches the full managed block (markers + content between them).
# DOTALL so `.` matches newlines.
_BLOCK_RE = re.compile(
    re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
    re.DOTALL,
)

# Regex matching the recheckpoint section between its markers. Uses
# DOTALL plus trailing-whitespace eating so a stripped section doesn't
# leave a double-blank-line gap behind.
_RECHECKPOINT_SECTION_RE = re.compile(
    re.escape(RECHECKPOINT_MARKER_START) + r".*?" + re.escape(RECHECKPOINT_MARKER_END) + r"\n*",
    re.DOTALL,
)


def load_template(single_checkpoint: bool = False) -> str:
    """Return the checkpoint instructions template content.

    When `single_checkpoint=True`, strip the recheckpoint-triggers section
    (delimited by `<!-- RECHECKPOINT-SECTION:START/END -->`) so the
    executor's instructions never mention recheckpointing. The canonical
    file still contains the section; only the rendered output differs.
    """
    content = _TEMPLATE_PATH.read_text(encoding="utf-8")
    if single_checkpoint:
        content = _RECHECKPOINT_SECTION_RE.sub("", content)
    return content


def _build_block(template: str) -> str:
    """Wrap *template* in marker comments."""
    return f"{MARKER_START}\n{template.strip()}\n{MARKER_END}"


def apply_instructions(target: Path) -> None:
    """Inject or update the managed checkpoint instructions block in *target*.

    - If *target* doesn't exist, create it with just the block.
    - If it exists but has no markers, append the block (with blank-line
      separation).
    - If it already has markers, replace the content between them.
    """
    template = load_template()
    block = _build_block(template)

    if not target.exists():
        target.write_text(block + "\n", encoding="utf-8")
        return

    content = target.read_text(encoding="utf-8")

    if MARKER_START in content:
        # Replace existing managed block
        content = _BLOCK_RE.sub(block, content, count=1)
    else:
        # Append with clean separation
        if not content.endswith("\n"):
            content += "\n"
        if not content.endswith("\n\n"):
            content += "\n"
        content += block + "\n"

    target.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Inject MassGen checkpoint instructions into CLAUDE.md",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("CLAUDE.md"),
        help="Path to the markdown file to patch (default: ./CLAUDE.md)",
    )
    args = parser.parse_args(argv)
    apply_instructions(args.target)
    print(f"Checkpoint instructions applied to {args.target}")


if __name__ == "__main__":
    main()
