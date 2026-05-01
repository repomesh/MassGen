"""Tests for `build_standalone_checkpoint_mcp_config`.

Mirrors `test_checkpoint_coordination.py::test_build_checkpoint_mcp_config_*`
patterns. The helper produces a stdio MCP server config the orchestrator can
inject into a single-agent's `backend_config["mcp_servers"]`.
"""

from __future__ import annotations

import pytest

from massgen.mcp_tools.subrun_utils import build_standalone_checkpoint_mcp_config


def test_basic_config():
    config = build_standalone_checkpoint_mcp_config(team_config_path="/path/to/team.yaml")
    assert config["name"] == "massgen_checkpoint_standalone"
    # Use "type" not "transport" — the MCP setup discriminates server kind by
    # the "type" key. A "transport" key is silently ignored and the server is
    # rejected as "missing type field" (verified in a real run).
    assert config["type"] == "stdio"
    assert config["command"] == "python"
    assert config["args"][0] == "-m"
    assert config["args"][1] == "massgen.mcp_tools.standalone.checkpoint_mcp_server"
    # team yaml passed via --config
    assert "--config" in config["args"]
    cfg_idx = config["args"].index("--config")
    assert config["args"][cfg_idx + 1] == "/path/to/team.yaml"


def test_team_config_required():
    """team_config_path is the standalone server's required CLI arg."""
    with pytest.raises(ValueError):
        build_standalone_checkpoint_mcp_config(team_config_path="")


def test_returns_serializable():
    """Config dict must be JSON-serializable for inclusion in YAML/json mcp_servers."""
    import json

    config = build_standalone_checkpoint_mcp_config(team_config_path="/path/to/team.yaml")
    json.dumps(config)  # must not raise
