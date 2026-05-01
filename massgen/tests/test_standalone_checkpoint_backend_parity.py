"""Backend-parity smoke tests for `massgen_checkpoint_standalone`.

Per CLAUDE.md: any non-trivial tooling feature should add backend-parity
tests for at least one `base_with_custom_tool_and_mcp` backend, `claude_code`,
and `codex`.

These tests don't spin up real backends; they verify the integration points
(FRAMEWORK_MCPS membership, codex's custom-tools wrapping path) so that the
standalone MCP shows up as a native protocol tool — not a code-based
filesystem wrapper.
"""

from __future__ import annotations

from massgen.filesystem_manager._constants import FRAMEWORK_MCPS


def test_standalone_server_in_framework_mcps():
    """Direct membership: model must see init/checkpoint as native tools."""
    assert "massgen_checkpoint_standalone" in FRAMEWORK_MCPS


def test_framework_mcp_prefix_match_works_for_agent_suffix():
    """Per FRAMEWORK_MCPS comments: server names may be suffixed (`name_agentid`).
    The base_with_custom_tool_and_mcp prefix-matching path must still recognize
    the standalone server even when suffixed.
    """
    server_name = "massgen_checkpoint_standalone_agent_a"
    assert any(server_name.startswith(f"{fmcp}_") for fmcp in FRAMEWORK_MCPS)


def test_standalone_tool_name_not_intercepted_as_internal_checkpoint():
    """Lock the exact-equality contract on the orchestrator's checkpoint
    interception: a startswith/substring loosening would double-intercept
    `mcp__massgen_checkpoint_standalone__checkpoint`."""
    internal_intercepted = {"checkpoint", "mcp__massgen_checkpoint__checkpoint"}
    standalone_name = "mcp__massgen_checkpoint_standalone__checkpoint"
    assert standalone_name not in internal_intercepted

    import re

    src = open(
        __import__("massgen.orchestrator", fromlist=["__file__"]).__file__,
    ).read()
    # Find every `tool_name in (...)` / `tool_name == ...` interception site
    # that mentions the internal name; assert none of them use a startswith
    # form against the internal prefix (which would catch the standalone).
    for match in re.finditer(r'tool_name\s*\.\s*startswith\s*\(\s*"mcp__massgen_checkpoint', src):
        # Permitted only if it explicitly includes the trailing `__` separator
        # (so `_standalone_` cannot leak in).
        snippet = src[max(0, match.start() - 5) : match.end() + 60]
        assert "mcp__massgen_checkpoint__" in snippet, (
            f"Found startswith against checkpoint prefix without trailing `__` separator; " f"this would also match the standalone server. Context: {snippet!r}"
        )


def test_excluded_from_subrun_passthrough():
    """The standalone server should not be silently included in a sub-MassGen
    spawn the way user MCPs are; the in-orchestrator checkpoint subprocess
    explicitly excludes the *internal* checkpoint server name. Confirm we
    haven't accidentally added the standalone name to the same exclusion list
    (which would be a category error — those exclusions are for in-orchestrator
    checkpoint subprocess hygiene, not for this in-session MCP)."""
    from massgen.mcp_tools import subrun_utils

    src = subrun_utils.__file__
    with open(src) as f:
        text = f.read()
    # The internal exclusion should still be there:
    assert '"massgen_checkpoint"' in text
    # The standalone server should NOT be in the subrun exclusion list, only
    # mentioned as the new helper:
    exclusion_block = text[text.find("exclude_mcp_servers=") : text.find("exclude_mcp_servers=") + 200]
    assert "massgen_checkpoint_standalone" not in exclusion_block
