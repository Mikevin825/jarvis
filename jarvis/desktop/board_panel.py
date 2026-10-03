"""The board meetings panel.

A window that shows past board meetings, lets you click into them to see
full detail, and has a button to convene a new meeting.

Follows the same pattern as the main desktop panel: tkinter only, queue-based
event handling, no framework.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from pathlib import Path
from typing import Callable

from ..board.dossier import parse_dossier
from ..board.store import MeetingStore, StoredMeeting
from ..board.surface import surface_meeting_card

DOSSIERS_DIR = Path(__file__).resolve().parent.parent / "board" / "dossiers"

# A dark, calm palette matching the main panel.
BG = "#14161a"
PANEL = "#1c1f26"
FG = "#e6e8ec"
MUTED = "#8b93a1"
ACCENT = "#5aa9e6"
DANGER = "#e06c75"
OK = "#98c379"


class BoardPanel:
    """The board meetings window.

    Shows a list of past meetings, lets you click into them to see full
    detail, and has a button to convene a new meeting.
    """

    def __init__(self, root: tk.Tk | None = None) -> None:
        self.root = root or tk.Tk()
        self.root.title("Board Meetings")
        self.root.configure(bg=BG)
        self.root.geometry("800x600")
        self.root.minsize(600, 400)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.events: queue.Queue = queue.Queue()
        self._selected_meeting: StoredMeeting | None = None

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

        # Header
        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")
        tk.Label(
            header, text="Board Meetings", bg=BG, fg=FG, font=bold, anchor="w"
        ).pack(side="left")
        self.count_label = tk.Label(
            header, text="", bg=BG, fg=MUTED, anchor="e"
        )
        self.count_label.pack(side="right")

        # Main content: meeting list on left, detail on right
        content = tk.Frame(outer, bg=BG)
        content.pack(fill="both", expand=True, pady=(10, 0))

        # Left: meeting list
        list_frame = tk.Frame(content, bg=PANEL)
        list_frame.pack(side="left", fill="y", padx=(0, 8))

        tk.Label(
            list_frame, text="Past Meetings", bg=PANEL, fg=MUTED, anchor="w"
        ).pack(fill="x", padx=10, pady=(8, 4))

        self.meeting_list = tk.Listbox(
            list_frame,
            bg=PANEL,
            fg=FG,
            relief="flat",
            highlightthickness=0,
            width=30,
            height=20,
        )
        self.meeting_list.pack(fill="both", expand=True, padx=4, pady=4)
        self.meeting_list.bind("<<ListboxSelect>>", self._on_meeting_selected)

        # Right: meeting detail
        detail_frame = tk.Frame(content, bg=PANEL)
        detail_frame.pack(side="left", fill="both", expand=True)

        self.detail_text = tk.Text(
            detail_frame,
            bg=PANEL,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            wrap="word",
            padx=10,
            pady=8,
            highlightthickness=0,
            state="disabled",
        )
        scroll = ttk.Scrollbar(detail_frame, command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.detail_text.pack(side="left", fill="both", expand=True)

        # Bottom: convene button
        controls = tk.Frame(outer, bg=BG)
        controls.pack(fill="x", pady=(10, 0))

        self.convene_btn = tk.Button(
            controls,
            text="Convene Board",
            command=self._convene_board,
            bg=ACCENT,
            fg="#0d1117",
            activebackground="#7fc0f0",
            activeforeground="#0d1117",
            relief="flat",
            padx=14,
            pady=6,
            cursor="hand2",
        )
        self.convene_btn.pack(side="left")

        self.status = tk.Label(
            controls, text="", bg=BG, fg=MUTED, anchor="w"
        )
        self.status.pack(side="left", padx=(10, 0))

        # Load meetings
        self._load_meetings()

    def _load_meetings(self) -> None:
        """Load past meetings from the store."""
        store = MeetingStore()
        store.load()
        meetings = store.all()

        self.meeting_list.delete(0, "end")
        for m in meetings:
            # Show question (truncated) and date
            question = m.question[:40] + "…" if len(m.question) > 40 else m.question
            date = m.created_at.strftime("%Y-%m-%d %H:%M")
            self.meeting_list.insert("end", f"{date} — {question}")

        self.count_label.configure(text=f"{len(meetings)} meeting(s)")

        if meetings:
            self.meeting_list.selection_set(0)
            self._show_meeting(meetings[0])

    def _on_meeting_selected(self, _event=None) -> None:
        """Handle meeting selection change."""
        selection = self.meeting_list.curselection()
        if not selection:
            return

        store = MeetingStore()
        store.load()
        meetings = store.all()
        index = selection[0]
        if index < len(meetings):
            self._show_meeting(meetings[index])

    def _show_meeting(self, meeting: StoredMeeting) -> None:
        """Show a meeting's full detail."""
        self._selected_meeting = meeting
        card = surface_meeting_card(None, meeting)

        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")

        # Question
        self.detail_text.insert("end", card["question"] + "\n", "heading")
        self.detail_text.insert("end", "\n")

        # Spoken summary
        if card["spoken"]:
            self.detail_text.insert("end", card["spoken"] + "\n", "subheading")
            self.detail_text.insert("end", "\n")

        # Split
        if card["split"]:
            self.detail_text.insert("end", f"Split: {card['split']}\n", "label")
            self.detail_text.insert("end", "\n")

        # Opinions
        for opinion in card["opinions"]:
            if opinion["error"]:
                self.detail_text.insert("end", f"• {opinion['seat_name']}: error — {opinion['error']}\n", "error")
            elif opinion["abstains"]:
                self.detail_text.insert("end", f"• {opinion['seat_name']}: abstained\n", "muted")
            else:
                self.detail_text.insert("end", f"• {opinion['seat_name']}: {opinion['position']}\n", "opinion")
                if opinion["citations"]:
                    cites = ", ".join(
                        f"{c['entry_id']} ({c['verification']})" for c in opinion["citations"]
                    )
                    self.detail_text.insert("end", f"  Citations: {cites}\n", "muted")
            self.detail_text.insert("end", "\n")

        # Discounts
        if card["discounts"]:
            self.detail_text.insert("end", "Blind spot discounts:\n", "label")
            for d in card["discounts"]:
                self.detail_text.insert("end", f"  - {d}\n", "muted")
            self.detail_text.insert("end", "\n")

        # Unverified flags
        if card["unverified_flags"]:
            self.detail_text.insert("end", "Unverified positions:\n", "label")
            for f in card["unverified_flags"]:
                self.detail_text.insert("end", f"  - {f}\n", "muted")
            self.detail_text.insert("end", "\n")

        # Cost and time
        self.detail_text.insert("end", f"Cost: ${card['total_cost_usd']:.4f}\n", "muted")
        self.detail_text.insert("end", f"Time: {card['total_wall_clock_s']:.1f}s\n", "muted")

        self.detail_text.configure(state="disabled")

        # Configure tags
        self.detail_text.tag_configure("heading", font=("TkDefaultFont", 12, "bold"), foreground=FG)
        self.detail_text.tag_configure("subheading", font=("TkDefaultFont", 10, "bold"), foreground=ACCENT)
        self.detail_text.tag_configure("label", font=("TkDefaultFont", 9, "bold"), foreground=MUTED)
        self.detail_text.tag_configure("opinion", foreground=FG)
        self.detail_text.tag_configure("muted", foreground=MUTED)
        self.detail_text.tag_configure("error", foreground=DANGER)

    def _convene_board(self) -> None:
        """Open a dialog to convene a new meeting."""
        # Simple dialog: ask for a question
        dialog = tk.Toplevel(self.root)
        dialog.title("Convene Board")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        dialog.resizable(False, False)

        frame = tk.Frame(dialog, bg=BG)
        frame.pack(fill="both", expand=True, padx=18, pady=16)

        tk.Label(
            frame,
            text="What should the board consider?",
            bg=BG,
            fg=FG,
            wraplength=400,
            justify="left",
            anchor="w",
        ).pack(fill="x")

        question_entry = tk.Entry(frame, bg=PANEL, fg=FG, insertbackground=FG, relief="flat")
        question_entry.pack(fill="x", pady=(8, 0))
        question_entry.focus_set()

        def convene() -> None:
            question = question_entry.get().strip()
            if not question:
                return
            dialog.destroy()
            self.status.configure(text="Convening board…", fg=ACCENT)
            # TODO: Actually convene the board via the tool
            # For now, just show a message
            self.status.configure(text="Board convened — check the inbox for results.", fg=OK)

        buttons = tk.Frame(frame, bg=BG)
        buttons.pack(fill="x", pady=(14, 0))

        tk.Button(
            buttons,
            text="Cancel",
            command=dialog.destroy,
            bg=PANEL,
            fg=FG,
            activebackground="#2a2f38",
            activeforeground=FG,
            relief="flat",
            padx=14,
            pady=6,
            cursor="hand2",
        ).pack(side="right")

        tk.Button(
            buttons,
            text="Convene",
            command=convene,
            bg=ACCENT,
            fg="#0d1117",
            activebackground="#7fc0f0",
            activeforeground="#0d1117",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
        ).pack(side="right", padx=(0, 8))

    # -- the pump -----------------------------------------------------------

    def _pump(self) -> None:
        """Drain queued events on the GUI thread, then reschedule."""
        try:
            while True:
                kind, a, b = self.events.get_nowait()
                # Handle events here if needed
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    # -- lifecycle ----------------------------------------------------------

    def _on_close(self) -> None:
        self.root.quit()
        self.root.destroy()

    def run(self) -> None:
        """Show the window. Blocks until closed."""
        self.root.mainloop()
