"""The desktop panel.

A small always-available window so JARVIS does not live in a terminal. It shows
what is happening, lets you talk with a button *or* the push-to-talk key, and —
most importantly — gives the confirmation gate somewhere real to ask.

Design notes worth keeping:

* **tkinter only.** It ships with Python, so this adds no dependency. The window
  is a plain panel, not a framework.
* **The loop stays the loop.** The panel observes `VoiceLoop` through callbacks
  (`on_state`, `on_turn`, `on_tool`). It does not reimplement any agent logic —
  the same discipline as the terminal and the voice layer.
* **All GUI work happens on the GUI thread.** Voice runs in a worker thread, so
  every callback from it is marshalled through a queue rather than touching
  widgets directly. Touching tkinter from another thread is how GUIs corrupt.
* **Click-to-talk as well as the key.** The button is the reliable path; the
  hotkey is the convenience. Neither depends on the other working.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from ..gate import ConfirmationRequest
from .gate import GuiGate

# A dark, calm palette. The panel should be glanceable, not attention-seeking.
BG = "#14161a"
PANEL = "#1c1f26"
FG = "#e6e8ec"
MUTED = "#8b93a1"
ACCENT = "#5aa9e6"
DANGER = "#e06c75"
OK = "#98c379"

STATE_TEXT = {
    "idle": "Ready",
    "recording": "Listening…",
    "transcribing": "Transcribing…",
    "thinking": "Thinking…",
    "speaking": "Speaking…",
    "tooshort": "Too short — hold the key while you speak",
    "heardnothing": "Heard nothing",
    "interrupted": "Interrupted",
    "error": "Error",
}


class DesktopPanel:
    """The window. Owns the Tk root and pumps voice callbacks onto it."""

    def __init__(
        self,
        loop,
        *,
        assistant_name: str = "JARVIS",
        ptt_description: str = "F9",
        interrupt_description: str = "ESC",
        on_quit=None,
    ) -> None:
        self.loop = loop
        self.name = assistant_name
        self.ptt_description = ptt_description
        self.interrupt_description = interrupt_description
        self.on_quit = on_quit

        self.events: queue.Queue = queue.Queue()
        self._pending_confirm: dict | None = None

        self.root = tk.Tk()
        self.root.title(f"{assistant_name}")
        self.root.configure(bg=BG)
        self.root.geometry("460x340")
        self.root.minsize(400, 300)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build()
        self._pump()

    # -- construction -------------------------------------------------------

    def _build(self) -> None:
        body = tkfont.nametofont("TkDefaultFont")
        body.configure(size=10)
        bold = body.copy()
        bold.configure(weight="bold", size=13)

        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True, padx=14, pady=12)

        # Header: name and live state
        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")
        tk.Label(
            header, text=self.name, bg=BG, fg=FG, font=bold, anchor="w"
        ).pack(side="left")
        self.state_label = tk.Label(
            header, text="Ready", bg=BG, fg=MUTED, anchor="e"
        )
        self.state_label.pack(side="right")

        # The conversation
        tk.Label(
            outer, text="", bg=BG, height=1
        ).pack()
        text_wrap = tk.Frame(outer, bg=PANEL)
        text_wrap.pack(fill="both", expand=True)

        self.transcript = tk.Text(
            text_wrap,
            bg=PANEL,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            wrap="word",
            padx=10,
            pady=8,
            height=10,
            state="disabled",
            highlightthickness=0,
        )
        scroll = ttk.Scrollbar(text_wrap, command=self.transcript.yview)
        self.transcript.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.transcript.pack(side="left", fill="both", expand=True)
        self.transcript.tag_configure("you", foreground=ACCENT)
        self.transcript.tag_configure("me", foreground=FG)
        self.transcript.tag_configure("meta", foreground=MUTED)
        self.transcript.tag_configure("bad", foreground=DANGER)
        self.transcript.tag_configure("good", foreground=OK)

        # Controls
        controls = tk.Frame(outer, bg=BG)
        controls.pack(fill="x", pady=(10, 0))

        self.talk_btn = tk.Button(
            controls,
            text="Hold to talk",
            command=lambda: None,
            bg=ACCENT,
            fg="#0d1117",
            activebackground="#7fc0f0",
            activeforeground="#0d1117",
            relief="flat",
            padx=14,
            pady=6,
            cursor="hand2",
        )
        self.talk_btn.pack(side="left")
        self.talk_btn.bind("<ButtonPress-1>", self._talk_press)
        self.talk_btn.bind("<ButtonRelease-1>", self._talk_release)

        tk.Button(
            controls,
            text="Stop",
            command=self._stop_speaking,
            bg=PANEL,
            fg=FG,
            activebackground="#2a2f38",
            activeforeground=FG,
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
        ).pack(side="left", padx=(8, 0))

        self.hint = tk.Label(
            controls,
            text=f"or hold {self.ptt_description}",
            bg=BG,
            fg=MUTED,
            anchor="e",
        )
        self.hint.pack(side="right")

    # -- talking ------------------------------------------------------------

    def _talk_press(self, _event=None) -> None:
        """Button down: start recording, exactly as holding the key does."""
        try:
            if not self.loop.recorder.recording:
                self.loop.recorder.start()
                self._set_state("recording")
        except Exception as exc:  # noqa: BLE001
            self._append("meta", f"cannot record: {exc}")

    def _talk_release(self, _event=None) -> None:
        """Button up: stop and hand the recording to the voice loop."""
        if not self.loop.recorder.recording:
            return
        path = self.loop.recorder.stop()
        if path is None:
            self._set_state("tooshort")
            return
        self.loop.submit_recording(path)

    def _stop_speaking(self) -> None:
        self.loop.interrupt()

    # -- voice loop observers (called from the voice thread) ----------------

    def on_state(self, state: str, detail: str = "") -> None:
        self.events.put(("state", state, detail))

    def on_turn(self, kind: str, text: str) -> None:
        self.events.put(("turn", kind, text))

    def on_tool(self, event) -> None:
        self.events.put(("tool", event, ""))

    # -- the pump -----------------------------------------------------------

    def _pump(self) -> None:
        """Drain queued voice events on the GUI thread, then reschedule."""
        try:
            while True:
                kind, a, b = self.events.get_nowait()
                if kind == "state":
                    self._set_state(a, b)
                elif kind == "turn":
                    if a == "hears":
                        self._append("you", f"you: {b}")
                    else:
                        self._append("me", f"{self.name}: {b}")
                elif kind == "tool":
                    if getattr(a, "gated", False):
                        self._append("meta", f"· {a.name} → waiting for your OK")
                    else:
                        tag = "good" if a.ok else "bad"
                        status = "ok" if a.ok else "failed"
                        self._append(tag, f"· {a.name} → {status}")
                elif kind == "confirm":
                    # The gate is waiting on this. Showing it here — on the GUI
                    # thread — is the whole point of queueing it.
                    self._show_confirmation(a, b)
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def _set_state(self, state: str, detail: str = "") -> None:
        text = STATE_TEXT.get(state, state.title())
        colour = MUTED
        if state == "recording":
            colour = DANGER
        elif state == "error":
            colour = DANGER
        elif state in ("thinking", "transcribing", "speaking"):
            colour = ACCENT
        self.state_label.configure(text=text, fg=colour)
        self.talk_btn.configure(
            text="Listening…" if state == "recording" else "Hold to talk"
        )
        if detail and state == "error":
            self._append("bad", detail)

    def _append(self, tag: str, line: str) -> None:
        self.transcript.configure(state="normal")
        self.transcript.insert("end", line + "\n", tag)
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    # -- the confirmation dialog --------------------------------------------

    def ask_confirmation(
        self, request: ConfirmationRequest, done: threading.Event, answer: list
    ) -> None:
        """Show the gate question. Called from the voice thread, so it only
        queues; the dialog itself is built on the GUI thread."""
        self.events.put(("confirm", request, (done, answer)))

    def _show_confirmation(self, request: ConfirmationRequest, result) -> None:
        done, answer = result
        if self._pending_confirm is not None:
            # One question at a time. A second request while one is open is
            # refused rather than stacked, so the user always knows what they
            # are answering.
            answer.append(False)
            done.set()
            return

        self._pending_confirm = {"done": done, "answer": answer}

        win = tk.Toplevel(self.root)
        win.title("Confirm")
        win.configure(bg=BG)
        win.transient(self.root)
        win.resizable(False, False)

        frame = tk.Frame(win, bg=BG)
        frame.pack(fill="both", expand=True, padx=18, pady=16)

        tk.Label(
            frame,
            text="JARVIS wants to do something that needs your say-so",
            bg=BG,
            fg=FG,
            wraplength=400,
            justify="left",
            anchor="w",
        ).pack(fill="x")

        tk.Label(
            frame,
            text=request.effect,
            bg=BG,
            fg=DANGER,
            wraplength=400,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(8, 0))

        if request.detail:
            detail = tk.Text(
                frame, bg=PANEL, fg=FG, relief="flat", wrap="word",
                height=3, padx=8, pady=6, highlightthickness=0,
            )
            detail.insert("1.0", request.detail)
            detail.configure(state="disabled")
            detail.pack(fill="x", pady=(8, 0))

        buttons = tk.Frame(frame, bg=BG)
        buttons.pack(fill="x", pady=(14, 0))

        def decide(approved: bool) -> None:
            if self._pending_confirm is None:
                return
            self._pending_confirm = None
            answer.append(approved)
            done.set()
            win.destroy()
            self._append(
                "meta",
                f"· {request.tool_name} → "
                + ("approved" if approved else "declined"),
            )

        deny = tk.Button(
            buttons, text="Don't allow", command=lambda: decide(False),
            bg=PANEL, fg=FG, activebackground="#2a2f38", activeforeground=FG,
            relief="flat", padx=14, pady=6, cursor="hand2",
        )
        deny.pack(side="right")

        allow = tk.Button(
            buttons, text="Allow", command=lambda: decide(True),
            bg=ACCENT, fg="#0d1117", activebackground="#7fc0f0",
            activeforeground="#0d1117", relief="flat", padx=16, pady=6,
            cursor="hand2",
        )
        allow.pack(side="right", padx=(0, 8))

        # Closing the window is a refusal, not an approval.
        win.protocol("WM_DELETE_WINDOW", lambda: decide(False))
        # Focus the safe choice, so an accidental Enter does not approve.
        deny.focus_set()

    # -- lifecycle ----------------------------------------------------------

    def _on_close(self) -> None:
        if self._pending_confirm is not None:
            # Never leave a gate waiting on a window that no longer exists.
            self._pending_confirm["answer"].append(False)
            self._pending_confirm["done"].set()
            self._pending_confirm = None
        self.loop.stop()
        if self.on_quit is not None:
            try:
                self.on_quit()
            except Exception:  # noqa: BLE001
                pass
        self.root.quit()
        self.root.destroy()

    def run(self) -> None:
        """Start the voice loop and show the window. Blocks until closed."""
        self.loop.start()
        self._append("meta", f"{self.name} is ready. Hold {self.ptt_description} "
                             "or use the button to talk.")
        self.root.mainloop()
