"""Tests for the orchestrator hook that injects the standalone checkpoint MCP.

The hook is gated on `coordination.standalone_checkpoint.enabled` and only
fires in single-agent configs.
"""

from __future__ import annotations

from types import SimpleNamespace

from massgen.agent_config import CoordinationConfig
from massgen.orchestrator import Orchestrator


def _stub_agent(mcp_servers: list | None = None) -> SimpleNamespace:
    """Mirror the real backend's __init__: a backend has *both* a config dict
    AND a runtime `mcp_servers` attribute that's bound from `config.get(...)`
    at construction. They diverge if `mcp_servers` is absent from the source
    YAML — `get(..., [])` returns a fresh default list that is NOT stored back
    in config. The orchestrator must mutate both."""
    initial = list(mcp_servers) if mcp_servers is not None else []
    backend = SimpleNamespace(
        config={"mcp_servers": list(initial)},
        mcp_servers=initial,
    )
    return SimpleNamespace(backend=backend)


def _make_orchestrator(coord: CoordinationConfig, agents: dict) -> Orchestrator:
    """Construct an Orchestrator without running its heavy __init__.

    `coord` lives on `self.config.coordination_config` in the real orchestrator;
    a previous version of this stub set `self.coordination_config` directly
    and masked a real registration bug — the gate read the wrong attribute and
    silently bailed in production while tests passed. Mirror the real shape.
    """
    orch = Orchestrator.__new__(Orchestrator)
    orch.agents = agents
    orch.config = SimpleNamespace(coordination_config=coord)
    return orch


def test_disabled_does_not_inject():
    coord = CoordinationConfig()  # all defaults; standalone_checkpoint_enabled=False
    agents = {"agent_a": _stub_agent()}
    orch = _make_orchestrator(coord, agents)
    orch._init_standalone_checkpoint_tool()
    assert agents["agent_a"].backend.config["mcp_servers"] == []


def test_enabled_single_agent_injects():
    coord = CoordinationConfig(
        standalone_checkpoint_enabled=True,
        standalone_checkpoint_team_config="/tmp/team.yaml",
    )
    agents = {"agent_a": _stub_agent()}
    orch = _make_orchestrator(coord, agents)
    orch._init_standalone_checkpoint_tool()
    backend = agents["agent_a"].backend
    config_servers = backend.config["mcp_servers"]
    runtime_servers = backend.mcp_servers
    # Both lists must include the standalone server. backend.mcp_servers is
    # the one the runtime actually iterates; if only config["mcp_servers"]
    # has it, the prompt promises a tool that was never registered.
    assert len(config_servers) == 1 and len(runtime_servers) == 1
    cfg = config_servers[0]
    runtime = runtime_servers[0]
    assert cfg["name"] == "massgen_checkpoint_standalone"
    assert cfg["type"] == "stdio"  # NOT "transport" — the MCP setup reads "type"
    assert "--config" in cfg["args"]
    assert cfg["args"][cfg["args"].index("--config") + 1] == "/tmp/team.yaml"
    assert cfg["args"][cfg["args"].index("--mode") + 1] == "generate"
    # Both list entries should be the same object/equal config.
    assert cfg == runtime


def test_mode_flags_propagate_to_server_args():
    """Mode flags from CoordinationConfig must reach the server's CLI args
    so the prompt and the server-side affordances stay in sync."""
    coord = CoordinationConfig(
        standalone_checkpoint_enabled=True,
        standalone_checkpoint_team_config="/tmp/team.yaml",
        standalone_checkpoint_mode="verify",
        standalone_checkpoint_single=True,
        standalone_checkpoint_include_workspace_context=True,
    )
    agents = {"agent_a": _stub_agent()}
    orch = _make_orchestrator(coord, agents)
    orch._init_standalone_checkpoint_tool()
    servers = agents["agent_a"].backend.config["mcp_servers"]
    assert len(servers) == 1
    server_args = servers[0]["args"]
    assert "--mode" in server_args
    assert server_args[server_args.index("--mode") + 1] == "verify"
    assert "--single-checkpoint" in server_args
    assert "--include-workspace-context" in server_args


def test_enabled_without_team_config_warns_and_skips(caplog):
    coord = CoordinationConfig(
        standalone_checkpoint_enabled=True,
        standalone_checkpoint_team_config=None,
    )
    agents = {"agent_a": _stub_agent()}
    orch = _make_orchestrator(coord, agents)
    orch._init_standalone_checkpoint_tool()
    assert agents["agent_a"].backend.config["mcp_servers"] == []


def test_multi_agent_skips_with_warning(caplog):
    """Standalone checkpoint is single-agent only; multi-agent must skip."""
    coord = CoordinationConfig(
        standalone_checkpoint_enabled=True,
        standalone_checkpoint_team_config="/tmp/team.yaml",
    )
    agents = {"agent_a": _stub_agent(), "agent_b": _stub_agent()}
    orch = _make_orchestrator(coord, agents)
    orch._init_standalone_checkpoint_tool()
    for agent in agents.values():
        assert agent.backend.config["mcp_servers"] == []


def test_idempotent():
    """Calling twice should not double-register."""
    coord = CoordinationConfig(
        standalone_checkpoint_enabled=True,
        standalone_checkpoint_team_config="/tmp/team.yaml",
    )
    agents = {"agent_a": _stub_agent()}
    orch = _make_orchestrator(coord, agents)
    orch._init_standalone_checkpoint_tool()
    orch._init_standalone_checkpoint_tool()
    servers = agents["agent_a"].backend.config["mcp_servers"]
    assert len(servers) == 1


def test_add_agent_strips_when_single_agent_invariant_breaks():
    """Single-agent run registers the MCP. add_agent breaks the invariant —
    the registration must be stripped from the original agent so the
    affordance the prompt promised matches what the runtime grants.
    """
    coord = CoordinationConfig(
        standalone_checkpoint_enabled=True,
        standalone_checkpoint_team_config="/tmp/team.yaml",
    )
    agents = {"agent_a": _stub_agent()}
    orch = _make_orchestrator(coord, agents)
    orch._init_standalone_checkpoint_tool()
    assert len(agents["agent_a"].backend.config["mcp_servers"]) == 1
    assert len(agents["agent_a"].backend.mcp_servers) == 1

    # Now simulate add_agent's post-mutation re-gate.
    agents["agent_b"] = _stub_agent()
    orch._init_standalone_checkpoint_tool()
    # Both lists on both agents must be empty.
    assert agents["agent_a"].backend.config["mcp_servers"] == []
    assert agents["agent_a"].backend.mcp_servers == []
    assert agents["agent_b"].backend.config["mcp_servers"] == []
    assert agents["agent_b"].backend.mcp_servers == []


def test_pre_wired_trajectory_arrives_in_server_args():
    """The orchestrator resolves the parent's trajectory path
    (from get_log_session_dir) and passes it as --default-trajectory-path so
    the agent's `init` call doesn't have to guess. This test asserts the arg
    lands in the spawn argv whenever a log session dir exists."""
    coord = CoordinationConfig(
        standalone_checkpoint_enabled=True,
        standalone_checkpoint_team_config="/tmp/team.yaml",
    )
    agents = {"agent_a": _stub_agent()}
    orch = _make_orchestrator(coord, agents)
    orch._init_standalone_checkpoint_tool()
    server_args = agents["agent_a"].backend.mcp_servers[0]["args"]
    # The test runner has logging set up; trajectory should always resolve.
    assert "--default-trajectory-path" in server_args
    traj = server_args[server_args.index("--default-trajectory-path") + 1]
    assert traj.endswith("events.jsonl")


def test_remove_agent_back_to_single_re_registers():
    """Remove a second agent back down to one — the gate now permits
    registration; the hook should add the server."""
    coord = CoordinationConfig(
        standalone_checkpoint_enabled=True,
        standalone_checkpoint_team_config="/tmp/team.yaml",
    )
    agents = {"agent_a": _stub_agent(), "agent_b": _stub_agent()}
    orch = _make_orchestrator(coord, agents)
    orch._init_standalone_checkpoint_tool()
    # multi-agent: nothing registered
    assert agents["agent_a"].backend.config["mcp_servers"] == []
    assert agents["agent_b"].backend.config["mcp_servers"] == []

    del agents["agent_b"]
    orch._init_standalone_checkpoint_tool()
    servers = agents["agent_a"].backend.config["mcp_servers"]
    assert len(servers) == 1
    assert servers[0]["name"] == "massgen_checkpoint_standalone"
