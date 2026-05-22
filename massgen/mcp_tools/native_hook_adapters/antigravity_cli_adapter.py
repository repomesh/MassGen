"""Antigravity CLI native hook adapter.

agy 1.0.x inherits Gemini CLI's hook *proto schema* (``exa.hooks_pb`` —
same ``BeforeTool`` / ``AfterTool`` / ``Stop`` event shape, same
``hooks.json`` payload structure) but stores it in a **standalone
``hooks.json`` file**, not embedded inside ``settings.json`` like
Gemini CLI does. Confirmed by inspecting binary strings on agy 1.0.1:

- ``PreToolHookArgs`` / ``PostToolHookArgs`` / ``StopHookArgs`` protos
- ``"Loaded hooks.json from %s: %d named hooks, %d total handlers"``
- ``"No hooks.json found at %s"``
- ``"failed to parse hooks.json at %s: %v"``
- ``Hooks json:"hooks"`` proto field tag (outer ``"hooks"`` key required)
- ``"json-hooks-enabled"`` / ``EnableJsonHooks`` cliSetting gate

Wiring lives in :class:`AntigravityCLIBackend` (see
``_write_hooks_json`` + ``_write_workspace_settings_json(has_hooks=True)``).
The hook script (``gemini_cli_hook_script.py``) is reusable as-is — the
JSON-on-stdin / JSON-on-stdout IPC contract is identical, only the
on-disk location of the config differs.
"""

from __future__ import annotations

from .gemini_cli_adapter import GeminiCLINativeHookAdapter


class AntigravityCLINativeHookAdapter(GeminiCLINativeHookAdapter):
    """Adapt MassGen hooks to agy's hooks.json format.

    Inherits ``build_native_hooks_config`` from
    :class:`GeminiCLINativeHookAdapter` unchanged — the returned
    ``{"hooks": {"BeforeTool": [...], "AfterTool": [...]}}`` payload is
    valid for both Gemini CLI ``settings.json["hooks"]`` and agy's
    standalone ``hooks.json``. The backend handles the destination-file
    divergence.
    """
