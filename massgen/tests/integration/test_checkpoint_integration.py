"""
Integration tests for checkpoint coordination mode.

Tests the full checkpoint lifecycle: main agent designation, solo mode,
checkpoint activation, workspace sync, and return to solo mode.

These tests use mock backends and don't require live API calls.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from massgen.coordination_tracker import CoordinationTracker, EventType
from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
    build_checkpoint_signal,
    format_checkpoint_result,
    write_checkpoint_signal,
)
from massgen.mcp_tools.hooks import CheckpointGatedHook, HookEvent
from massgen.mcp_tools.subrun_utils import (
    build_checkpoint_mcp_config,
    generate_subrun_config,
    sync_workspace_from_subrun,
)


@pytest.mark.integration
class TestCheckpointLifecycle:
    """Test the full checkpoint lifecycle end-to-end."""

    def test_checkpoint_signal_roundtrip(self, tmp_path):
        """Signal write -> read -> validate roundtrip."""
        signal = build_checkpoint_signal(
            task="Build the REST API",
            context="We need auth and CRUD endpoints",
            expected_actions=[
                {"tool": "mcp__vercel__deploy", "description": "Deploy to Vercel"},
            ],
        )

        # Write signal
        write_checkpoint_signal(signal, tmp_path)

        # Read it back
        signal_file = tmp_path / ".massgen_checkpoint_signal.json"
        assert signal_file.exists()
        loaded = json.loads(signal_file.read_text())

        assert loaded["type"] == "checkpoint"
        assert loaded["task"] == "Build the REST API"
        assert loaded["context"] == "We need auth and CRUD endpoints"
        assert len(loaded["expected_actions"]) == 1
        assert loaded["expected_actions"][0]["tool"] == "mcp__vercel__deploy"

    def test_checkpoint_result_formatting(self):
        """Checkpoint result should contain all required fields."""
        result = format_checkpoint_result(
            consensus="Built REST API with JWT auth, CRUD for users and posts",
            workspace_changes=[
                {"file": "src/routes/auth.py", "change": "created"},
                {"file": "src/routes/users.py", "change": "created"},
                {"file": "src/routes/posts.py", "change": "created"},
                {"file": "src/models.py", "change": "modified"},
            ],
            action_results=[
                {
                    "tool": "mcp__vercel__deploy",
                    "executed": True,
                    "result": {"url": "https://api.example.vercel.app"},
                },
            ],
        )

        assert "consensus" in result
        assert len(result["workspace_changes"]) == 4
        assert result["action_results"][0]["executed"] is True

    def test_gated_hook_integration_with_multiple_patterns(self):
        """Gated hook should correctly handle multiple patterns."""
        hook = CheckpointGatedHook(
            gated_patterns=[
                "mcp__vercel__deploy*",
                "mcp__github__delete_*",
                "mcp__*__production_*",
            ],
        )

        # Should block: matches vercel deploy
        event1 = HookEvent(
            hook_type="PreToolUse",
            session_id="test",
            orchestrator_id="orch",
            agent_id="agent1",
            timestamp=MagicMock(),
            tool_name="mcp__vercel__deploy_production",
            tool_input={},
        )
        assert hook(event1).decision == "deny"

        # Should block: matches github delete
        event2 = HookEvent(
            hook_type="PreToolUse",
            session_id="test",
            orchestrator_id="orch",
            agent_id="agent1",
            timestamp=MagicMock(),
            tool_name="mcp__github__delete_branch",
            tool_input={},
        )
        assert hook(event2).decision == "deny"

        # Should block: matches production wildcard
        event3 = HookEvent(
            hook_type="PreToolUse",
            session_id="test",
            orchestrator_id="orch",
            agent_id="agent1",
            timestamp=MagicMock(),
            tool_name="mcp__aws__production_deploy",
            tool_input={},
        )
        assert hook(event3).decision == "deny"

        # Should allow: doesn't match any pattern
        event4 = HookEvent(
            hook_type="PreToolUse",
            session_id="test",
            orchestrator_id="orch",
            agent_id="agent1",
            timestamp=MagicMock(),
            tool_name="mcp__github__create_pr",
            tool_input={},
        )
        assert hook(event4).decision == "allow"


@pytest.mark.integration
class TestSubrunConfigGeneration:
    """Test that subrun configs are correctly generated for checkpoints."""

    def test_generate_subrun_config_removes_main_agent(self):
        """Subrun config should remove main_agent flags."""
        parent_config = {
            "agents": [
                {
                    "id": "architect",
                    "main_agent": True,
                    "backend": {"type": "claude", "model": "sonnet"},
                },
                {
                    "id": "builder",
                    "backend": {"type": "openai", "model": "gpt-4"},
                },
            ],
            "orchestrator": {
                "coordination": {"max_rounds": 5},
            },
        }
        config = generate_subrun_config(
            parent_config,
            workspace=Path("/tmp/subrun"),
        )

        # No agent should have main_agent
        for agent in config["agents"]:
            assert "main_agent" not in agent

    def test_generate_subrun_config_excludes_checkpoint_mcp(self):
        """Subrun config should exclude checkpoint MCP to prevent recursion."""
        parent_config = {
            "agents": [
                {
                    "id": "architect",
                    "main_agent": True,
                    "backend": {
                        "type": "claude",
                        "model": "sonnet",
                        "mcp_servers": [
                            {"name": "checkpoint", "transport": "stdio"},
                            {"name": "workspace_tools", "transport": "stdio"},
                        ],
                    },
                },
            ],
        }
        config = generate_subrun_config(
            parent_config,
            workspace=Path("/tmp/subrun"),
        )

        # checkpoint MCP should be removed
        mcp_names = [s["name"] for s in config["agents"][0]["backend"].get("mcp_servers", [])]
        assert "checkpoint" not in mcp_names
        assert "workspace_tools" in mcp_names

    def test_build_checkpoint_mcp_config(self):
        """Checkpoint MCP config should be correctly formatted."""
        config = build_checkpoint_mcp_config(
            workspace_path=Path("/tmp/workspace"),
            agent_id="architect",
            gated_patterns=["mcp__vercel__deploy*"],
        )

        assert config["name"] == "massgen_checkpoint"
        assert config["type"] == "stdio"
        assert "--workspace-path" in config["args"]
        assert "/tmp/workspace" in config["args"]
        assert "--agent-id" in config["args"]
        assert "architect" in config["args"]


@pytest.mark.integration
class TestWorkspaceSync:
    """Test workspace synchronization after checkpoint."""

    def test_sync_workspace_from_subrun(self, tmp_path):
        """Workspace changes should sync correctly from subrun to main."""
        # Set up subrun workspace with files
        subrun_ws = tmp_path / "subrun"
        (subrun_ws / "workspaces" / "agent1").mkdir(parents=True)
        (subrun_ws / "workspaces" / "agent1" / "src").mkdir()
        (subrun_ws / "workspaces" / "agent1" / "src" / "app.py").write_text(
            "# New app code",
        )
        (subrun_ws / "workspaces" / "agent1" / "README.md").write_text(
            "# Project README",
        )

        # Set up main workspace (empty)
        main_ws = tmp_path / "main"
        main_ws.mkdir()

        changes = sync_workspace_from_subrun(subrun_ws, main_ws)

        assert len(changes) == 2
        assert (main_ws / "src" / "app.py").exists()
        assert (main_ws / "README.md").exists()

        # Verify change types
        change_files = {c["file"] for c in changes}
        assert "src/app.py" in change_files
        assert "README.md" in change_files

    def test_sync_workspace_skips_status_files(self, tmp_path):
        """Workspace sync should skip internal status files."""
        subrun_ws = tmp_path / "subrun"
        subrun_ws.mkdir()
        (subrun_ws / "answer.txt").write_text("answer content")
        (subrun_ws / "status.json").write_text("{}")
        (subrun_ws / "real_file.py").write_text("# real code")

        main_ws = tmp_path / "main"
        main_ws.mkdir()

        changes = sync_workspace_from_subrun(subrun_ws, main_ws)

        # Only real_file.py should be synced
        assert len(changes) == 1
        assert changes[0]["file"] == "real_file.py"


@pytest.mark.integration
class TestCoordinationTrackerCheckpointEvents:
    """Test checkpoint events in coordination tracker."""

    def test_full_checkpoint_event_lifecycle(self):
        """Tracker should record all checkpoint lifecycle events."""
        tracker = CoordinationTracker()

        # Simulate checkpoint lifecycle
        tracker._add_event(
            EventType.CHECKPOINT_CALLED,
            agent_id="architect",
            details="Checkpoint #1: Build the frontend",
        )
        tracker._add_event(
            EventType.CHECKPOINT_AGENTS_ACTIVATED,
            agent_id=None,
            details="All 3 agents activated",
        )
        tracker._add_event(
            EventType.CHECKPOINT_CONSENSUS_REACHED,
            agent_id=None,
            details="Consensus on frontend implementation",
        )
        tracker._add_event(
            EventType.CHECKPOINT_ACTION_EXECUTED,
            agent_id=None,
            details="Executed: mcp__vercel__deploy",
            context={"tool": "mcp__vercel__deploy", "success": True},
        )
        tracker._add_event(
            EventType.CHECKPOINT_COMPLETED,
            agent_id="architect",
            details="Checkpoint #1 completed, returning to solo mode",
        )

        # Verify all events recorded
        checkpoint_events = [e for e in tracker.events if e.event_type.value.startswith("checkpoint_")]
        assert len(checkpoint_events) == 5

        event_types = [e.event_type for e in checkpoint_events]
        assert EventType.CHECKPOINT_CALLED in event_types
        assert EventType.CHECKPOINT_AGENTS_ACTIVATED in event_types
        assert EventType.CHECKPOINT_CONSENSUS_REACHED in event_types
        assert EventType.CHECKPOINT_ACTION_EXECUTED in event_types
        assert EventType.CHECKPOINT_COMPLETED in event_types
