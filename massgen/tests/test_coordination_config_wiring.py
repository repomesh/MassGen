"""Regression tests for coordination config parser wiring.

These tests protect the YAML -> CoordinationConfig path from silent drift as
new coordination fields are added.
"""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path

from massgen.agent_config import CoordinationConfig


def test_yaml_addressable_coordination_fields_have_parser_coverage():
    """Every dataclass field must be parsed, transformed, or explicitly internal."""
    dataclass_fields = {field.name for field in fields(CoordinationConfig)}

    yaml_keys = CoordinationConfig.yaml_coordination_keys()
    nested_aliases = CoordinationConfig.nested_coordination_field_aliases()
    internal_fields = CoordinationConfig.non_yaml_coordination_fields()

    classified_fields = set(yaml_keys)
    for alias_targets in nested_aliases.values():
        classified_fields.update(alias_targets)
    classified_fields.update(internal_fields)

    assert not (yaml_keys & internal_fields), "Fields cannot be both YAML-addressable and internal"
    assert not (set().union(*nested_aliases.values()) & internal_fields), "Nested alias targets cannot be internal"
    assert classified_fields == dataclass_fields


def test_cli_parse_coordination_config_delegates_to_central_parser(monkeypatch):
    from massgen import cli

    sentinel = object()
    calls: list[dict[str, object]] = []

    def fake_from_dict(raw):
        calls.append(raw)
        return sentinel

    monkeypatch.setattr(CoordinationConfig, "from_dict", fake_from_dict, raising=False)

    raw = {"fast_iteration_mode": True}
    assert cli._parse_coordination_config(raw) is sentinel
    assert calls == [raw]


def test_nested_coordination_sections_still_parse():
    config = CoordinationConfig.from_dict(
        {
            "persona_generator": {
                "enabled": True,
                "diversity_mode": "methodology",
                "persona_guidelines": "Make the agents disagree usefully.",
                "persist_across_turns": True,
                "after_first_answer": "keep",
            },
            "evaluation_criteria_generator": {
                "enabled": True,
                "persist_across_turns": True,
                "min_criteria": 6,
                "max_criteria": 9,
            },
            "prompt_improver": {
                "enabled": True,
                "persist_across_turns": True,
            },
            "task_decomposer": {
                "enabled": True,
                "decomposition_guidelines": "Prefer independent chunks.",
                "timeout_seconds": 120,
            },
            "subagent_orchestrator": {
                "enabled": True,
                "inherit_spawning_agent_backend": True,
                "shared_child_team_types": ["round_evaluator", "builder"],
                "final_answer_strategy": "synthesize",
            },
            "standalone_checkpoint": {
                "enabled": True,
                "team_config": "/tmp/team.yaml",
                "mode": "verify",
                "single_checkpoint": True,
                "include_workspace_context": True,
            },
        },
    )

    assert config.persona_generator.enabled is True
    assert config.persona_generator.diversity_mode == "methodology"
    assert config.persona_generator.persona_guidelines == "Make the agents disagree usefully."
    assert config.persona_generator.persist_across_turns is True
    assert config.persona_generator.after_first_answer == "keep"
    assert config.evaluation_criteria_generator.enabled is True
    assert config.evaluation_criteria_generator.persist_across_turns is True
    assert config.evaluation_criteria_generator.min_criteria == 6
    assert config.evaluation_criteria_generator.max_criteria == 9
    assert config.prompt_improver.enabled is True
    assert config.prompt_improver.persist_across_turns is True
    assert config.task_decomposer.enabled is True
    assert config.task_decomposer.decomposition_guidelines == "Prefer independent chunks."
    assert config.task_decomposer.timeout_seconds == 120
    assert config.subagent_orchestrator is not None
    assert config.subagent_orchestrator.enabled is True
    assert config.subagent_orchestrator.inherit_spawning_agent_backend is True
    assert config.subagent_orchestrator.shared_child_team_types == ["round_evaluator", "builder"]
    assert config.subagent_orchestrator.final_answer_strategy == "synthesize"
    assert config.standalone_checkpoint_enabled is True
    assert config.standalone_checkpoint_team_config == "/tmp/team.yaml"
    assert config.standalone_checkpoint_mode == "verify"
    assert config.standalone_checkpoint_single is True
    assert config.standalone_checkpoint_include_workspace_context is True


def test_drift_prone_scalar_fields_parse_from_yaml_dict():
    config = CoordinationConfig.from_dict(
        {
            "plan_depth": "deep",
            "plan_target_steps": 42,
            "plan_target_chunks": 4,
            "subagent_min_timeout": 30,
            "subagent_max_timeout": 900,
            "subagent_default_timeout": 120,
        },
    )

    assert config.plan_depth == "deep"
    assert config.plan_target_steps == 42
    assert config.plan_target_chunks == 4
    assert config.subagent_min_timeout == 30
    assert config.subagent_max_timeout == 900
    assert config.subagent_default_timeout == 120


def test_documented_coordination_yaml_fields_are_parser_covered():
    docs_path = Path("docs/source/reference/yaml_schema.rst")
    docs_text = docs_path.read_text()
    documented_fields = set(re.findall(r"\* - ``([^`]+)``", docs_text))

    documented_coordination_fields = {
        "plan_depth",
        "plan_target_steps",
        "plan_target_chunks",
        "subagent_default_timeout",
        "subagent_min_timeout",
        "subagent_max_timeout",
    }

    assert documented_coordination_fields <= documented_fields
    assert documented_coordination_fields <= CoordinationConfig.yaml_coordination_keys()
