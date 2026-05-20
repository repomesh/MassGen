"""Antigravity CLI native hook adapter.

agy 1.0.0 inherits Gemini CLI's hook framework verbatim — same ``exa.hooks_pb``
proto schema, same ``BeforeTool`` / ``AfterTool`` / ``Stop`` event names,
same ``settings.json`` shape, and the same ``~/.gemini/trusted_hooks.json``
trust file. Confirmed by inspecting binary strings on agy 1.0.0:

- ``PreToolHookArgs`` / ``PostToolHookArgs`` / ``StopHookArgs`` protos
- ``"Loaded hooks.json from %s: %d named hooks, %d total handlers"``
- ``"json-hooks-enabled"`` / ``"trustedHooks"`` literals

The hook script (``gemini_cli_hook_script.py``) is reusable as-is — the
JSON-on-stdin / JSON-on-stdout contract is identical. This adapter exists
only so backend dispatch is explicit and we can diverge cleanly if Google
changes the hook protocol in a future agy release.
"""

from __future__ import annotations

from .gemini_cli_adapter import GeminiCLINativeHookAdapter


class AntigravityCLINativeHookAdapter(GeminiCLINativeHookAdapter):
    """Adapt MassGen hooks to agy's settings.json hook format.

    Identical to ``GeminiCLINativeHookAdapter`` because agy v1.0.0 reuses
    the Gemini CLI ``exa.hooks_pb`` proto schema. Subclassed solely so
    backend dispatch is explicit and divergence is cheap if needed later.
    """
