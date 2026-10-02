"""The scout's tool base.

Re-exports the main tool types so the scout module is self-contained.
The scout uses the same Tool/ToolError/ToolRegistry pattern as the rest of
JARVIS — no new abstractions, just a separate module for the scout's tools.
"""

from ..tools.base import Tool, ToolError, ToolRegistry, ToolResult

__all__ = ["Tool", "ToolError", "ToolRegistry", "ToolResult"]
