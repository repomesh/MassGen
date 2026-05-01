"""Tests for `coordination.standalone_checkpoint` wiring.

This block toggles whether the standalone checkpoint MCP server
(`massgen/mcp_tools/standalone/checkpoint_mcp_server.py`) is exposed inside a
normal MassGen run. It is off by default and only meaningful in single-agent
configs.
"""

from __future__ import annotations

from massgen.agent_config import CoordinationConfig
from massgen.cli import _parse_coordination_config


def test_default_is_disabled():
    config = _parse_coordination_config({})
    assert config.standalone_checkpoint_enabled is False
    assert config.standalone_checkpoint_team_config is None
    assert config.standalone_checkpoint_mode == "generate"
    assert config.standalone_checkpoint_single is False
    assert config.standalone_checkpoint_include_workspace_context is False


def test_enabled_with_team_config():
    config = _parse_coordination_config(
        {
            "standalone_checkpoint": {
                "enabled": True,
                "team_config": "/tmp/team.yaml",
                "mode": "verify",
                "single_checkpoint": True,
                "include_workspace_context": True,
            },
        },
    )
    assert config.standalone_checkpoint_enabled is True
    assert config.standalone_checkpoint_team_config == "/tmp/team.yaml"
    assert config.standalone_checkpoint_mode == "verify"
    assert config.standalone_checkpoint_single is True
    assert config.standalone_checkpoint_include_workspace_context is True


def test_dataclass_defaults_match_parser():
    """CoordinationConfig dataclass defaults must match the parser defaults."""
    cc = CoordinationConfig()
    assert cc.standalone_checkpoint_enabled is False
    assert cc.standalone_checkpoint_team_config is None
    assert cc.standalone_checkpoint_mode == "generate"
    assert cc.standalone_checkpoint_single is False
    assert cc.standalone_checkpoint_include_workspace_context is False


def test_invalid_mode_falls_back_to_generate_with_warning():
    """Unknown mode strings are normalized to 'generate' rather than crashing,
    AND a warning is emitted so the typo is visible (silent coercion would
    let 'verfy' run the wrong mode unnoticed)."""
    from loguru import logger

    captured: list[str] = []
    sink_id = logger.add(lambda msg: captured.append(str(msg)), level="WARNING")
    try:
        config = _parse_coordination_config(
            {"standalone_checkpoint": {"enabled": True, "mode": "unknown_mode"}},
        )
    finally:
        logger.remove(sink_id)
    assert config.standalone_checkpoint_mode == "generate"
    warning_text = " ".join(captured)
    assert "unknown_mode" in warning_text
    assert "generate" in warning_text
