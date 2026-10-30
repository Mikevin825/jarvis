"""The tool registry, assembled.

Adding a capability: write one self-contained module next to these and add its
`build()` to the list below. The core loop never changes.
"""

from __future__ import annotations

from dataclasses import replace

from ..memory import MemoryStore
from ..presence import tools as presence_tools
from . import apps, browser, clock, external, files, member_consultation, memory, messages, notes, reminders, system, weather, web, whatsapp
from .base import Tool, ToolError, ToolRegistry, ToolResult

__all__ = ["Tool", "ToolError", "ToolRegistry", "ToolResult", "build_registry"]

# Modules whose tools need no external state. One line per capability, forever.
# CAUTION: external module contains powerful, gated tools that can close apps,
# run arbitrary commands, access any file, and interact with the GUI. All are
# consequential and require explicit user confirmation.
_MODULES = (clock, weather, notes, apps, messages, files, system, browser, reminders, presence_tools, web, whatsapp, external, member_consultation)


def build_registry(
    memory_store: MemoryStore | None = None,
    extra_gated: tuple = (),
    ungated: tuple = (),
    provider=None,
) -> ToolRegistry:
    """Assemble every tool.

    `memory_store` is passed in rather than built here so the store is a single
    shared object: the same one the brain reads from at the start of a turn is
    the one the memory tools write to.

    `extra_gated` / `ungated` come from `rails` in config.yaml, so the safety
    posture can be tightened (or deliberately loosened) without a code change.

    `provider` is passed to tools that need a model to reason (e.g. the board).
    """
    registry = ToolRegistry()
    for module in _MODULES:
        for tool in module.build():
            registry.register(tool)

    if memory_store is not None:
        for tool in memory.build(memory_store):
            registry.register(tool)

    # Board tools need a provider to reason
    if provider is not None:
        from ..board.tool import build as build_board
        for tool in build_board(provider=provider):
            registry.register(tool)

    # Member consultation tools need a provider to invoke the model
    if provider is not None:
        from . import member_consultation
        member_consultation.set_provider(provider)

    # Apply the config-level posture last, so it can adjust any tool.
    for name in extra_gated:
        tool = registry.get(name)
        if tool is not None and not tool.consequential:
            registry._tools[name] = replace(tool, consequential=True, confirm_prompt=(
                tool.confirm_prompt or "you asked for this one to require confirmation"
            ))
    for name in ungated:
        tool = registry.get(name)
        if tool is not None and tool.consequential:
            registry._tools[name] = replace(tool, consequential=False)

    return registry