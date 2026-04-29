"""Tests for TUI copy mode (Ctrl+Shift+S).

Copy mode disables Textual's terminal mouse tracking so the user can drag-select
text natively. The banner widget reflects whether copy mode is active.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult
from textual.binding import Binding

from massgen.frontend.displays.textual_widgets.copy_mode_banner import CopyModeBanner


class _CopyModeApp(App):
    """Minimal app exercising the copy-mode toggle and banner.

    Mirrors the binding + action contract used on TextualApp without depending
    on the full coordination display.
    """

    BINDINGS = [
        Binding("ctrl+shift+s", "toggle_copy_mode", "Copy Mode", priority=True, show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.mouse_calls: list[bool] = []

    def compose(self) -> ComposeResult:
        yield CopyModeBanner(id="copy_banner")

    def _set_terminal_mouse_capture(self, enabled: bool) -> None:
        self.mouse_calls.append(enabled)

    def action_toggle_copy_mode(self) -> None:
        banner = self.query_one(CopyModeBanner)
        new_state = not banner.active
        banner.set_active(new_state)
        self._set_terminal_mouse_capture(not new_state)


@pytest.mark.asyncio
async def test_banner_starts_hidden():
    app = _CopyModeApp()
    async with app.run_test(headless=True) as pilot:
        await pilot.pause()
        banner = app.query_one(CopyModeBanner)
        assert banner.active is False
        assert "hidden" in banner.classes


@pytest.mark.asyncio
async def test_ctrl_shift_s_activates_copy_mode():
    app = _CopyModeApp()
    async with app.run_test(headless=True) as pilot:
        await pilot.press("ctrl+shift+s")
        await pilot.pause()

        banner = app.query_one(CopyModeBanner)
        assert banner.active is True
        assert "hidden" not in banner.classes
        assert app.mouse_calls == [False]


@pytest.mark.asyncio
async def test_ctrl_shift_s_toggles_off_again():
    app = _CopyModeApp()
    async with app.run_test(headless=True) as pilot:
        await pilot.press("ctrl+shift+s")
        await pilot.pause()
        await pilot.press("ctrl+shift+s")
        await pilot.pause()

        banner = app.query_one(CopyModeBanner)
        assert banner.active is False
        assert "hidden" in banner.classes
        assert app.mouse_calls == [False, True]


def test_banner_set_active_directly():
    """Unit test on the widget without an App harness."""
    banner = CopyModeBanner(id="copy_banner")
    assert banner.active is False
    assert "hidden" in banner.classes

    banner.set_active(True)
    assert banner.active is True
    assert "hidden" not in banner.classes

    banner.set_active(False)
    assert banner.active is False
    assert "hidden" in banner.classes


def test_set_terminal_mouse_capture_calls_driver_enable():
    from massgen.frontend.displays.textual_widgets.copy_mode_banner import (
        set_terminal_mouse_capture,
    )

    driver = MagicMock(spec=["_enable_mouse_support", "_disable_mouse_support"])
    set_terminal_mouse_capture(driver, True)
    driver._enable_mouse_support.assert_called_once_with()
    driver._disable_mouse_support.assert_not_called()


def test_set_terminal_mouse_capture_calls_driver_disable():
    from massgen.frontend.displays.textual_widgets.copy_mode_banner import (
        set_terminal_mouse_capture,
    )

    driver = MagicMock(spec=["_enable_mouse_support", "_disable_mouse_support"])
    set_terminal_mouse_capture(driver, False)
    driver._disable_mouse_support.assert_called_once_with()
    driver._enable_mouse_support.assert_not_called()


def test_set_terminal_mouse_capture_no_driver_is_safe():
    """Headless driver lacks the private methods — call must be a silent no-op."""
    from massgen.frontend.displays.textual_widgets.copy_mode_banner import (
        set_terminal_mouse_capture,
    )

    set_terminal_mouse_capture(None, True)
    set_terminal_mouse_capture(None, False)


def test_set_terminal_mouse_capture_missing_method_no_op():
    """If the driver doesn't expose the private method, fall through silently."""
    from massgen.frontend.displays.textual_widgets.copy_mode_banner import (
        set_terminal_mouse_capture,
    )

    set_terminal_mouse_capture(SimpleNamespace(), True)
    set_terminal_mouse_capture(SimpleNamespace(), False)
