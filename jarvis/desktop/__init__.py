"""The desktop panel: JARVIS outside the terminal.

Two pieces, both deliberately small:

* `DesktopPanel` — the window. Observes the voice loop; never reimplements it.
* `GuiGate` — the confirmation gate, with somewhere real to ask.

The window is a plain tkinter panel, so this adds no dependency beyond what
Python already ships.
"""

from .gate import GuiGate
from .panel import DesktopPanel

__all__ = ["DesktopPanel", "GuiGate"]
