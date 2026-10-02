"""A GUI confirmation gate.

The terminal gate cannot serve a window — there is no terminal to prompt in. This
one puts the question in front of the user where they actually are, with the
exact action spelled out, and waits for a real click.

Two properties carried over from the terminal gate, both deliberate:

* **Defaults to no.** The approve button is never the one under the cursor by
  accident, and closing the dialog is a refusal.
* **Times out to no.** A prompt nobody answers must not hang the assistant
  forever, so it expires into the safe default (do nothing) and leaves a note.
"""

from __future__ import annotations

import queue
import threading
from typing import Callable

from ..gate import ConfirmationRequest, Decision


class GuiGate:
    """Asks for confirmation in the desktop window.

    The gate is called from the conversation thread, but the dialog must be
    shown from the GUI thread, so the request is handed across a queue and the
    caller waits on an event. That wait is bounded — an unanswered prompt
    expires rather than deadlocking.
    """

    def __init__(
        self,
        ask: Callable[[ConfirmationRequest, threading.Event, list], None],
        timeout_seconds: float = 120.0,
    ) -> None:
        self._ask = ask
        self.timeout_seconds = timeout_seconds

    def confirm(self, request: ConfirmationRequest) -> Decision:
        done = threading.Event()
        answer: list[bool] = []

        try:
            self._ask(request, done, answer)
        except Exception as exc:  # noqa: BLE001 - a broken prompt must fail closed
            return Decision(False, f"could not ask for confirmation: {exc}")

        if not done.wait(timeout=self.timeout_seconds):
            return Decision(
                False,
                f"no answer within {int(self.timeout_seconds)}s; did nothing",
            )

        if answer and answer[0]:
            return Decision(True, "confirmed in the window")
        return Decision(False, "declined in the window")
