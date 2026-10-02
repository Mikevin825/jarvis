"""The tool registry, assembled.

Adding a capability: write one self-contained module next to these and add its
`build()` to the list below. The core loop never changes.
"""

from __future__ import annotations

from . import apps, clock, messages, notes, weather
from .base import Tool, ToolError, ToolRegistry, ToolResult

__all__ = ["Tool", "ToolError", "ToolRegistry", "ToolResult", "build_registry"]

# Each entry is one capability module. One line per capability, forever.
_MODULES = (clock, weather, notes, apps, messages)


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for module in _MODULES:
        for tool in module.build():
            registry.register(tool)
    return registry
