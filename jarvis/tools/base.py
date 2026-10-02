"""The tool registry.

A tool is a named capability with a description written for a *reader* (the
model picks tools from these descriptions, so vague ones cause wrong calls) and
a typed list of inputs.

This registry is the thing you extend forever. Adding a capability means writing
one self-contained tool and registering it — never editing the core loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

ToolFunc = Callable[..., str]


class ToolError(Exception):
    """A tool failed in a way worth explaining to the model.

    Raising this returns a plain-language message to the model rather than
    crashing the loop, so the agent can reason about the failure and tell the
    user what went wrong.
    """


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    func: ToolFunc
    # Consequential tools send, spend, delete, or change settings. They must not
    # run on assumed permission — Tier 6 builds the gate that stops them until
    # the user says yes. Until then they refuse, which is the safe default.
    consequential: bool = False
    # What the user is told before a consequential tool runs.
    confirm_prompt: str = ""

    def declaration(self) -> dict:
        """The provider-neutral shape handed to the model each turn."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass
class ToolResult:
    name: str
    ok: bool
    content: str
    call_id: str | None = None


@dataclass
class ToolRegistry:
    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def declarations(self) -> list[dict]:
        return [t.declaration() for t in self._tools.values()]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def run(self, name: str, args: dict, call_id: str | None = None) -> ToolResult:
        """Look a tool up by name, run it, and never raise.

        Failures come back as an `ok=False` result carrying a plain-language
        explanation, which is returned to the model so it can recover or explain.
        """
        tool = self._tools.get(name)
        if tool is None:
            known = ", ".join(self.names()) or "none"
            return ToolResult(
                name=name,
                ok=False,
                content=f"There is no tool called '{name}'. Available tools: {known}.",
                call_id=call_id,
            )

        if tool.consequential:
            # Tier 6 replaces this with a real confirmation gate. Refusing by
            # default is deliberate: an unbuilt gate must fail closed.
            return ToolResult(
                name=name,
                ok=False,
                content=(
                    f"'{name}' is a consequential action and is blocked pending "
                    f"the user's explicit confirmation: "
                    f"{tool.confirm_prompt or 'it changes something.'} "
                    "Tell the user exactly what you intend to do and ask them to "
                    "confirm. Do not attempt it again in this turn."
                ),
                call_id=call_id,
            )

        try:
            return ToolResult(name=name, ok=True, content=tool.func(**args), call_id=call_id)
        except ToolError as exc:
            return ToolResult(name=name, ok=False, content=str(exc), call_id=call_id)
        except TypeError as exc:
            # Wrong or missing arguments — a bad call, not a broken tool.
            return ToolResult(
                name=name,
                ok=False,
                content=(
                    f"'{name}' was called with the wrong arguments ({exc}). "
                    f"Expected inputs: {_describe(tool.parameters)}."
                ),
                call_id=call_id,
            )
        except Exception as exc:  # noqa: BLE001 - a tool must never crash the loop
            return ToolResult(
                name=name,
                ok=False,
                content=f"'{name}' failed unexpectedly: {type(exc).__name__}: {exc}",
                call_id=call_id,
            )


def _describe(parameters: dict) -> str:
    props: dict[str, Any] = parameters.get("properties") or {}
    required = set(parameters.get("required") or [])
    if not props:
        return "no inputs"
    parts = []
    for key, spec in props.items():
        mark = "" if key in required else " (optional)"
        parts.append(f"{key}: {spec.get('type', 'any').lower()}{mark}")
    return ", ".join(parts)
