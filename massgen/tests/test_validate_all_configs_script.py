"""Tests for scripts/validate_all_configs.py release-gate behavior."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize(
    ("config_extra", "expected_key"),
    [
        (
            {"orchestrator": {"coordination": {"fast_interation_mode": True}}},
            "fast_interation_mode",
        ),
        (
            {"orchestrator": {"voting_sensitivty": "balanced"}},
            "voting_sensitivty",
        ),
        (
            {"timeout_settings": {"orchestrator_timout_seconds": 60}},
            "orchestrator_timout_seconds",
        ),
    ],
)
def test_validate_all_configs_strict_fails_on_unknown_config_key(
    tmp_path: Path,
    config_extra: dict,
    expected_key: str,
):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "typo.yaml"
    config = {
        "agent": {
            "id": "agent-1",
            "backend": {"type": "openai", "model": "gpt-4o"},
        },
    }
    config.update(config_extra)
    config_path.write_text(
        yaml.safe_dump(config),
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_all_configs.py",
            "--strict",
            "--directory",
            str(config_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert expected_key in output
