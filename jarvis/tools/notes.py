"""Notes — the "manage my notes and documents" capability.

Notes are plain markdown files under `state/notes/`. Plain files on purpose:
memory and notes you cannot open, read, and edit by hand are notes you cannot
trust.
"""

from __future__ import annotations

import re
from datetime import datetime

from ..paths import NOTES_DIR, ensure_dirs
from .base import Tool, ToolError

_UNSAFE = re.compile(r"[^A-Za-z0-9 ._-]")


def _slug(title: str) -> str:
    """Turn a title into a safe filename. Never lets a title escape the dir."""
    cleaned = _UNSAFE.sub("", title).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:80] or "untitled"


def _path_for(title: str):
    ensure_dirs()
    return NOTES_DIR / f"{_slug(title)}.md"


def _all_notes() -> list:
    ensure_dirs()
    return sorted(NOTES_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)


def list_notes() -> str:
    notes = _all_notes()
    if not notes:
        return "There are no notes yet."
    lines = []
    for p in notes:
        body = p.read_text(encoding="utf-8")
        first = next(
            (ln.strip() for ln in body.splitlines() if ln.strip()), "(empty)"
        )
        preview = first[:70] + ("…" if len(first) > 70 else "")
        lines.append(f"- {p.stem} — {preview}")
    return f"{len(notes)} note(s):\n" + "\n".join(lines)


def read_note(title: str) -> str:
    path = _path_for(title)
    if not path.exists():
        available = ", ".join(p.stem for p in _all_notes()) or "none"
        raise ToolError(
            f"There is no note called '{title}'. Existing notes: {available}."
        )
    return f"# {path.stem}\n\n{path.read_text(encoding='utf-8')}"


def create_note(title: str, body: str) -> str:
    path = _path_for(title)
    if path.exists():
        # Overwriting would destroy what is already there, so refuse and let the
        # model ask the user what they want.
        raise ToolError(
            f"A note called '{path.stem}' already exists. Read it first, or "
            "choose a different title. Overwriting needs the user's say-so."
        )
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    path.write_text(f"{body}\n\n_created {stamp}_\n", encoding="utf-8")
    return f"Created note '{path.stem}'."


def append_note(title: str, text: str) -> str:
    """Add to an existing note without destroying it. Safe: purely additive."""
    path = _path_for(title)
    if not path.exists():
        raise ToolError(f"There is no note called '{title}' to add to.")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n{text}\n\n_updated {stamp}_\n")
    return f"Added to note '{path.stem}'."


def delete_note(title: str) -> str:
    path = _path_for(title)
    if not path.exists():
        raise ToolError(f"There is no note called '{title}' to delete.")
    path.unlink()
    return f"Deleted note '{path.stem}'."


def build() -> list[Tool]:
    return [
        Tool(
            name="list_notes",
            description=(
                "Use this to see what notes exist. Call it when the user asks what "
                "notes they have, or before searching for one."
            ),
            parameters={"type": "OBJECT", "properties": {}},
            func=list_notes,
        ),
        Tool(
            name="read_note",
            description=(
                "Use this to read the full contents of one note by its title."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING", "description": "The note's title."}
                },
                "required": ["title"],
            },
            func=read_note,
        ),
        Tool(
            name="create_note",
            description=(
                "Use this to write a new note. Fails if a note with that title "
                "already exists, so nothing is ever overwritten by accident."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING", "description": "Short title for the note."},
                    "body": {"type": "STRING", "description": "The note's contents."},
                },
                "required": ["title", "body"],
            },
            func=create_note,
        ),
        Tool(
            name="append_note",
            description=(
                "Use this to add text to the end of an existing note. This is "
                "additive and never removes what is already there."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING", "description": "The note's title."},
                    "text": {"type": "STRING", "description": "Text to append."},
                },
                "required": ["title", "text"],
            },
            func=append_note,
        ),
        Tool(
            name="delete_note",
            description=(
                "Use this to delete a note permanently. This destroys data, so it "
                "requires the user's explicit confirmation first."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING", "description": "The note to delete."}
                },
                "required": ["title"],
            },
            func=delete_note,
            consequential=True,
            confirm_prompt="permanently deletes a note from disk, and it cannot be undone",
        ),
    ]
