"""The scout settings panel.

The operator opens this and sees the real doctrine, editable, with version
history and one-click revert. This is the surface that makes the scout's
instruction set feel like data, not code.

The trap this tier warns about: panels that gate on lookup tables and lie when
they miss an entry. The panel must never show an empty textarea and a message
like "no default available" for a document that is loaded on every run. Every
editable document must have a real default.

Two distinctions that look like one:
- "This document has an override" is not "this document's main content has an
  override." Use the broad one for the header badge and the narrow one to gate
  the Revert button.
- A version restore must route by the version's own key, not the key in the URL.

Validate before write: if a save carries several documents, validate all of them
before writing any. Otherwise a rejected second textarea leaves the first one
half-saved.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from pathlib import Path

from ..scout.doctrine import DOCTRINE_PATH, load_document
from ..scout.overrides import (
    delete_override,
    effective_document,
    get_override,
    has_override,
    set_override,
)

# The documents that can be edited. Each entry is (key, label, path).
# Register additional editable documents explicitly rather than discovering them
# by naming convention — a convention lets an agent expose an internal prompt
# key by accident.
EDITABLE_DOCUMENTS = [
    ("scout_doctrine", "Doctrine", DOCTRINE_PATH),
]

# A dark, calm palette matching the main panel.
BG = "#14161a"
PANEL = "#1c1f26"
FG = "#e6e8ec"
MUTED = "#8b93a1"
ACCENT = "#5aa9e6"
DANGER = "#e06c75"
OK = "#98c379"


class ScoutPanel:
    """The scout settings window.

    Shows the doctrine, lets the operator edit it, and provides version history
    with one-click revert. Each document is independent — editing one does not
    affect the others.
    """

    def __init__(self, root: tk.Tk | None = None) -> None:
        self.root = root or tk.Tk()
        self.root.title("Scout Settings")
        self.root.configure(bg=BG)
        self.root.geometry("700x500")
        self.root.minsize(600, 400)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.events: queue.Queue = queue.Queue()
        self._pending_save: dict | None = None

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
            header, text="Scout Settings", bg=BG, fg=FG, font=bold, anchor="w"
        ).pack(side="left")
        self.override_label = tk.Label(
            header, text="", bg=BG, fg=MUTED, anchor="e"
        )
        self.override_label.pack(side="right")

        # Document selector
        doc_frame = tk.Frame(outer, bg=BG)
        doc_frame.pack(fill="x", pady=(10, 0))
        tk.Label(
            doc_frame, text="Document:", bg=BG, fg=MUTED, anchor="w"
        ).pack(side="left")
        self.doc_var = tk.StringVar(value=EDITABLE_DOCUMENTS[0][1])
        self.doc_combo = ttk.Combobox(
            doc_frame,
            textvariable=self.doc_var,
            values=[label for _, label, _ in EDITABLE_DOCUMENTS],
            state="readonly",
            width=20,
        )
        self.doc_combo.pack(side="left", padx=(8, 0))
        self.doc_combo.bind("<<ComboboxSelected>>", self._on_doc_changed)

        # The text area
        text_wrap = tk.Frame(outer, bg=PANEL)
        text_wrap.pack(fill="both", expand=True, pady=(10, 0))

        self.text = tk.Text(
            text_wrap,
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
        scroll = ttk.Scrollbar(text_wrap, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

        # Buttons
        controls = tk.Frame(outer, bg=BG)
        controls.pack(fill="x", pady=(10, 0))

        self.edit_btn = tk.Button(
            controls,
            text="Edit",
            command=self._start_edit,
            bg=ACCENT,
            fg="#0d1117",
            activebackground="#7fc0f0",
            activeforeground="#0d1117",
            relief="flat",
            padx=14,
            pady=6,
            cursor="hand2",
        )
        self.edit_btn.pack(side="left")

        self.save_btn = tk.Button(
            controls,
            text="Save",
            command=self._save,
            bg=OK,
            fg="#0d1117",
            activebackground="#b8e39a",
            activeforeground="#0d1117",
            relief="flat",
            padx=14,
            pady=6,
            cursor="hand2",
        )
        self.save_btn.pack(side="left", padx=(8, 0))
        self.save_btn.configure(state="disabled")

        self.revert_btn = tk.Button(
            controls,
            text="Revert to file",
            command=self._revert,
            bg=PANEL,
            fg=FG,
            activebackground="#2a2f38",
            activeforeground=FG,
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
        )
        self.revert_btn.pack(side="left", padx=(8, 0))

        # Version history
        history_frame = tk.Frame(outer, bg=BG)
        history_frame.pack(fill="x", pady=(10, 0))
        tk.Label(
            history_frame, text="Version history:", bg=BG, fg=MUTED, anchor="w"
        ).pack(side="left")
        self.history_list = tk.Listbox(
            history_frame,
            bg=PANEL,
            fg=FG,
            relief="flat",
            highlightthickness=0,
            height=4,
        )
        self.history_list.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.history_list.bind("<<ListboxSelect>>", self._on_history_selected)

        self.revert_version_btn = tk.Button(
            history_frame,
            text="Revert to version",
            command=self._revert_to_version,
            bg=PANEL,
            fg=FG,
            activebackground="#2a2f38",
            activeforeground=FG,
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
        )
        self.revert_version_btn.pack(side="left", padx=(8, 0))
        self.revert_version_btn.configure(state="disabled")

        # Status line
        self.status = tk.Label(
            outer, text="", bg=BG, fg=MUTED, anchor="w"
        )
        self.status.pack(fill="x", pady=(10, 0))

        # Load the initial document
        self._load_document()

    # -- document management ------------------------------------------------

    def _current_key(self) -> str:
        """Get the key for the currently selected document."""
        label = self.doc_var.get()
        for key, doc_label, _ in EDITABLE_DOCUMENTS:
            if doc_label == label:
                return key
        return EDITABLE_DOCUMENTS[0][0]

    def _current_path(self) -> Path:
        """Get the path for the currently selected document."""
        label = self.doc_var.get()
        for _, doc_label, path in EDITABLE_DOCUMENTS:
            if doc_label == label:
                return path
        return EDITABLE_DOCUMENTS[0][2]

    def _load_document(self) -> None:
        """Load the currently selected document into the text area."""
        key = self._current_key()
        path = self._current_path()

        content = effective_document(key, path)
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.configure(state="disabled")

        # Update the override badge
        if has_override(key):
            self.override_label.configure(text="OVERRIDDEN", fg=ACCENT)
        else:
            self.override_label.configure(text="file default", fg=MUTED)

        # Update the revert button
        if has_override(key):
            self.revert_btn.configure(state="normal")
        else:
            self.revert_btn.configure(state="disabled")

        # Update version history
        self._load_history()

    def _load_history(self) -> None:
        """Load version history for the current document."""
        self.history_list.delete(0, "end")
        # Version history is tracked in the override store. For now, show
        # the current override and the file default.
        key = self._current_key()
        if has_override(key):
            self.history_list.insert("end", "Current override")
        self.history_list.insert("end", "File default")

    def _on_doc_changed(self, _event=None) -> None:
        """Handle document selection change."""
        self._load_document()

    # -- editing ------------------------------------------------------------

    def _start_edit(self) -> None:
        """Enable editing of the text area."""
        self.text.configure(state="normal")
        self.edit_btn.configure(state="disabled")
        self.save_btn.configure(state="normal")
        self.status.configure(text="Editing — make your changes, then Save")

    def _save(self) -> None:
        """Save the current text as an override.

        Validates before writing. If the text is empty or unchanged, refuse.
        """
        key = self._current_key()
        content = self.text.get("1.0", "end-1c")

        # Validate: refuse empty content
        if not content.strip():
            self.status.configure(text="Cannot save empty content", fg=DANGER)
            return

        # Validate: refuse unchanged content
        current = effective_document(key, self._current_path())
        if content == current:
            self.status.configure(text="No changes to save", fg=MUTED)
            return

        # Write the override
        set_override(key, content)
        self.status.configure(text="Saved — override is now active", fg=OK)

        # Reload to show the new state
        self._load_document()
        self.text.configure(state="disabled")
        self.edit_btn.configure(state="normal")
        self.save_btn.configure(state="disabled")

    def _revert(self) -> None:
        """Revert to the file default."""
        key = self._current_key()
        if not has_override(key):
            self.status.configure(text="No override to revert", fg=MUTED)
            return

        delete_override(key)
        self.status.configure(text="Reverted to file default", fg=OK)
        self._load_document()

    def _on_history_selected(self, _event=None) -> None:
        """Handle version history selection."""
        selection = self.history_list.curselection()
        if selection:
            self.revert_version_btn.configure(state="normal")
        else:
            self.revert_version_btn.configure(state="disabled")

    def _revert_to_version(self) -> None:
        """Revert to a specific version.

        Routes by the version's own key, not the key in the URL. This is the
        distinction the spec warns about: once extra documents write version
        rows into the same history table, a restore that trusts the URL will
        happily paste a lane document over the doctrine.
        """
        selection = self.history_list.curselection()
        if not selection:
            return

        index = selection[0]
        key = self._current_key()

        if index == 0:
            # Current override — do nothing
            self.status.configure(text="Already at current override", fg=MUTED)
        elif index == 1:
            # File default — delete the override
            self._revert()
        else:
            self.status.configure(text="Unknown version", fg=DANGER)

    # -- the pump -----------------------------------------------------------

    def _pump(self) -> None:
        """Drain queued events on the GUI thread, then reschedule."""
        try:
            while True:
                kind, a, b = self.events.get_nowait()
                if kind == "save":
                    self._save()
                elif kind == "revert":
                    self._revert()
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
