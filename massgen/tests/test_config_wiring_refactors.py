"""Regression tests for release-critical config wiring refactors."""

from __future__ import annotations

from dataclasses import fields

from massgen.agent_config import AgentConfig, TimeoutConfig


def test_timeout_settings_fields_have_parser_coverage():
    """Every TimeoutConfig field should be YAML-addressable and centrally parsed."""
    dataclass_fields = {field.name for field in fields(TimeoutConfig)}

    assert TimeoutConfig.yaml_timeout_keys() == dataclass_fields


def test_cli_parse_timeout_config_delegates_to_central_parser(monkeypatch):
    from massgen import cli

    sentinel = object()
    calls: list[dict[str, object]] = []

    def fake_from_dict(raw):
        calls.append(raw)
        return sentinel

    monkeypatch.setattr(TimeoutConfig, "from_dict", fake_from_dict, raising=False)

    raw = {"orchestrator_timeout_seconds": 60}
    assert cli._parse_timeout_config(raw) is sentinel
    assert calls == [raw]


def test_orchestrator_runtime_keys_cover_applied_agent_fields():
    """Runtime keys should be owned by AgentConfig, not repeated in CLI glue."""
    expected_keys = {
        "voting_sensitivity",
        "voting_threshold",
        "max_new_answers_per_agent",
        "max_new_answers_global",
        "answer_novelty_requirement",
        "fairness_enabled",
        "fairness_lead_cap_answers",
        "max_midstream_injections_per_round",
        "defer_peer_updates_until_restart",
        "allow_midstream_peer_updates_before_checklist_submit",
        "defer_voting_until_all_answered",
        "coordination_mode",
        "presenter_agent",
        "final_answer_strategy",
        "checklist_require_gap_report",
        "gap_report_mode",
        "max_checklist_calls_per_round",
        "checklist_first_answer",
        "debug_final_answer",
        "skip_final_presentation",
        "skip_voting",
        "disable_injection",
        "skip_coordination_rounds",
    }

    assert expected_keys <= AgentConfig.orchestrator_runtime_keys()


def test_cli_apply_orchestrator_runtime_params_delegates_to_agent_config(monkeypatch):
    from massgen import cli

    calls: list[tuple[AgentConfig, dict[str, object]]] = []

    def fake_apply(self, raw):
        calls.append((self, raw))

    monkeypatch.setattr(AgentConfig, "apply_orchestrator_config", fake_apply, raising=False)

    config = AgentConfig()
    raw = {"voting_threshold": 3}
    cli._apply_orchestrator_runtime_params(config, raw)

    assert calls == [(config, raw)]


def test_apply_orchestrator_config_wires_checklist_runtime_fields():
    config = AgentConfig()

    config.apply_orchestrator_config(
        {
            "checklist_require_gap_report": False,
            "max_checklist_calls_per_round": 3,
            "checklist_first_answer": True,
        },
    )

    assert config.checklist_require_gap_report is False
    assert config.gap_report_mode == "none"
    assert config.max_checklist_calls_per_round == 3
    assert config.checklist_first_answer is True
