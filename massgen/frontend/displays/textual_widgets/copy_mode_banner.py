"""Copy mode banner for the MassGen TUI.

Shows a banner indicating copy mode is active. While active, terminal mouse
tracking is disabled so the user can drag-select text the way they would in
any other terminal app.
"""

from typing import Any

from textual.widgets import Static

# Single source of truth for the copy-mode keybinding so the banner hint, the
# notify toast, and the BINDINGS entry don't drift apart.
COPY_MODE_BINDING = "ctrl+shift+s"
COPY_MODE_HINT = f"📋 Copy mode — drag to select, Cmd/Ctrl+C in your terminal to copy. " f"Press {COPY_MODE_BINDING.replace('+', '+').title()} to exit."


def set_terminal_mouse_capture(driver: Any, enabled: bool) -> None:
    """Toggle the terminal's mouse-tracking escape codes via the Textual driver.

    Textual 6.x has no public API for this. The private driver methods are
    stable in practice; we no-op silently on drivers that don't expose them
    (notably HeadlessDriver in tests).
    """
    if driver is None:
        return
    fn = getattr(driver, "_enable_mouse_support" if enabled else "_disable_mouse_support", None)
    if fn is None:
        return
    try:
        fn()
    except Exception:
        # Driver may already be torn down; nothing useful to do.
        pass


class CopyModeBanner(Static):
    """Banner that indicates copy mode is on.

    Hidden by default. `.copy-mode-banner` and `.hidden` styles live in base.tcss.
    """

    DEFAULT_CSS = ""

    HINT = COPY_MODE_HINT

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(self.HINT, id=id, classes="copy-mode-banner hidden")
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def set_active(self, active: bool) -> None:
        """Show or hide the banner."""
        self._active = active
        if active:
            self.remove_class("hidden")
        else:
            self.add_class("hidden")
