"""The confirmation gate.

Sits between the model choosing a consequential tool and that tool running. It
covers typed, spoken, and heartbeat-initiated actions alike, because every one of
them flows through the same registry.

The rules this encodes, from the spec:

* **Hard gate on consequential actions.** Anything that sends, spends, deletes,
  or changes a setting stops and gets an explicit yes before it runs.
* **Read-only actions flow freely.** The gate is never consulted for them.
* **Confirmation is per-action and does not generalize.** Approving one send
  does not pre-authorise the next. Nothing here caches an approval.
* **Never block forever waiting on a human.** A gate with no human present
  returns "no" immediately and leaves a note, rather than hanging the loop.
* **Fail closed.** The default gate denies everything. An unconfigured or
  unreachable gate must never mean "allowed".
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ConfirmationRequest:
    """What the user is being asked to approve, stated plainly."""

    tool_name: str
    args: dict
    # One line describing the effect, e.g. "sends a message to another person".
    effect: str
    # The actual action, for showing exactly what would happen.
    detail: str

    def describe(self) -> str:
        lines = [f"{self.tool_name} — {self.effect}"]
        if self.detail:
            lines.append(f"  {self.detail}")
        return "\n".join(lines)


@dataclass(frozen=True)
class Decision:
    approved: bool
    # Why, for the audit log and for the model.
    reason: str = ""

    def __bool__(self) -> bool:  # lets `if gate.confirm(...)` read naturally
        return self.approved


class Gate(Protocol):
    def confirm(self, request: ConfirmationRequest) -> Decision:  # pragma: no cover
        ...


class DenyAllGate:
    """The safe default: refuse everything, explain nothing was run.

    Used when no gate is configured. Deliberately the fallback — an assistant
    that cannot reach its gate must not assume permission.
    """

    def confirm(self, request: ConfirmationRequest) -> Decision:
        return Decision(False, "no confirmation gate is configured")


class NoHumanGate:
    """For the heartbeat: never blocks, never assumes permission.

    A background action that pauses to ask for approval and finds nobody there
    must not hang — a proactive system that deadlocks on an unreachable person
    stops working silently. So this returns "no" at once, and the caller leaves
    a note so the user can decide later.
    """

    def __init__(self, on_defer=None) -> None:
        self.on_defer = on_defer

    def confirm(self, request: ConfirmationRequest) -> Decision:
        if self.on_defer is not None:
            try:
                self.on_defer(request)
            except Exception:  # noqa: BLE001 - deferring must not break the loop
                pass
        return Decision(
            False,
            "no one is present to confirm; left a note instead of acting",
        )


class CliGate:
    """Asks in the terminal, one action at a time.

    If stdin is not a terminal there is nobody to ask, so it denies rather than
    reading whatever happens to be on stdin — a piped script must never be able
    to stand in for a human saying yes.
    """

    def __init__(self, input_fn=input, output=None, interactive: bool | None = None) -> None:
        self._input = input_fn
        self._out = output or sys.stdout
        self._interactive = (
            sys.stdin.isatty() if interactive is None else interactive
        )

    def confirm(self, request: ConfirmationRequest) -> Decision:
        if not self._interactive:
            return Decision(
                False,
                "no interactive terminal to confirm in; refusing rather than "
                "assuming permission",
            )

        print("\n" + "─" * 62, file=self._out)
        print("JARVIS wants to do something that needs your say-so:", file=self._out)
        print(f"  {request.effect}", file=self._out)
        if request.detail:
            print(f"  {request.detail}", file=self._out)
        print("─" * 62, file=self._out)

        try:
            answer = self._input("Allow this? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(file=self._out)
            return Decision(False, "cancelled at the prompt")

        if answer in ("y", "yes"):
            return Decision(True, "confirmed by the user")
        return Decision(False, "declined by the user")


class AutoApproveGate:
    """Approves everything. For tests only — never wire this up as a default."""

    def confirm(self, request: ConfirmationRequest) -> Decision:
        return Decision(True, "auto-approved (test gate)")
