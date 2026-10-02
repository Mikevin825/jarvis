"""The tool registry, assembled.

Adding a capability: write one self-contained module next to these and add its
`build()` to the list below. The core loop never changes.
"""

from __future__ import annotations

from ..memory import MemoryStore
from . import apps, clock, memory, messages, notes, weather
from .base import Tool, ToolError, ToolRegistry, ToolResult

__all__ = ["Tool", "ToolError", "ToolRegistry", "ToolResult", "build_registry"]

# Modules whose tools need no external state. One line per capability, forever.
_MODULES = (clock, weather, notes, apps, messages)


def build_registry(memory_store: MemoryStore | None = None) -> ToolRegistry:
    """Assemble every tool.

    `memory_store` is passed in rather than built here so the store is a single
    shared object: the same one the brain reads from at the start of a turn is
    the one the memory tools write to.
    """
    registry = ToolRegistry()
    for module in _MODULES:
        for tool in module.build():
            registry.register(tool)

    if memory_store is not None:
        for tool in memory.build(memory_store):
            registry.register(tool)

    return registry
