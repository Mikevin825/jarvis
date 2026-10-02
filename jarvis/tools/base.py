"""The tool registry.

A tool is a named capability with a description written for a *reader* (the
model picks tools from these descriptions, so vague ones cause wrong calls) and
a typed list of inputs.

This registry is the thing you extend forever. Adding a capability means writing
one self-contained tool and registering it — never editing the core loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:  # avoids a circular import: gate -> tools is not needed
    from ..gate import Gate

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
    # run on assumed permission — the gate in `jarvis.gate` stops them until the
    # user says yes, every single time.
    consequential: bool = False
    # What the user is told before a consequential tool runs: one line stating
    # the effect, in plain language.
    confirm_prompt: str = ""
    # Which of the user's "never without asking" categories this falls under.
    # Free-form, used for the audit log and for grouping in config.
    category: str = ""

    def declaration(self) -> dict:
        """The provider-neutral shape handed to the model each turn."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def describe_action(self, args: dict) -> str:
        """A concrete, human-readable statement of what this call would do.

        The user is approving *this action*, not the tool in the abstract, so
        the actual arguments belong in front of them.
        """
        if not args:
            return f"{self.name} (no arguments)"
        rendered = ", ".join(f"{k}={v!r}" for k, v in args.items())
        return f"{self.name}({rendered})"


@dataclass
class ToolResult:
    name: str
    ok: bool
    content: str
    call_id: str | None = None
    # True when the result came from the gate rather than from running the tool,
    # so the caller can tell "declined" apart from "failed".
    gated: bool = False


@dataclass
class ToolRegistry:
    _tools: dict[str, Tool] = field(default_factory=dict)
    # The confirmation gate. Defaults to denying everything: an assistant that
    # cannot reach its gate must not assume permission.
    gate: "Gate | None" = None
    # Called for every consequential attempt, allowed or not, so the audit trail
    # records what was asked for as well as what happened.
    on_audit: Callable[[str, str, str], None] | None = None

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

    def consequential_names(self) -> list[str]:
        return sorted(n for n, t in self._tools.items() if t.consequential)

    def _audit(self, source: str, status: str, detail: str) -> None:
        if self.on_audit is not None:
            try:
                self.on_audit(source, status, detail)
            except Exception:  # noqa: BLE001 - logging must not break a turn
                pass

    def run(self, name: str, args: dict, call_id: str | None = None) -> ToolResult:
        """Look a tool up by name, run it, and never raise.

        Consequential tools are routed through the gate first. Everything else
        runs straight away — read-only actions flow freely.

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
            allowed = self._check_gate(tool, args)
            if allowed is not None:
                return allowed

        try:
            result = ToolResult(
                name=name, ok=True, content=tool.func(**args), call_id=call_id
            )
            if tool.consequential:
                self._audit(name, "ran", tool.describe_action(args))
            return result
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

    def _check_gate(self, tool: Tool, args: dict) -> ToolResult | None:
        """Ask the gate. Returns a blocking ToolResult, or None to proceed."""
        from ..gate import ConfirmationRequest, DenyAllGate

        request = ConfirmationRequest(
            tool_name=tool.name,
            args=args,
            effect=tool.confirm_prompt or "it does something hard to undo",
            detail=tool.describe_action(args),
        )

        gate = self.gate if self.gate is not None else DenyAllGate()
        try:
            decision = gate.confirm(request)
        except Exception as exc:  # noqa: BLE001 - a broken gate must fail closed
            self._audit(tool.name, "gate-error", f"{type(exc).__name__}: {exc}")
            return ToolResult(
                name=tool.name,
                ok=False,
                content=(
                    f"'{tool.name}' could not be confirmed because the "
                    f"confirmation step failed ({type(exc).__name__}). It was "
                    "not run. Tell the user."
                ),
                gated=True,
            )

        if decision.approved:
            self._audit(tool.name, "approved", tool.describe_action(args))
            return None

        self._audit(tool.name, "declined", f"{tool.describe_action(args)} — {decision.reason}")
        return ToolResult(
            name=tool.name,
            ok=False,
            gated=True,
            content=(
                f"'{tool.name}' was NOT run. {decision.reason or 'Not approved.'} "
                f"Reason it needs approval: {request.effect}. "
                "Do not retry it in this turn. Tell the user plainly that it did "
                "not happen and why, and let them decide what to do next."
            ),
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
