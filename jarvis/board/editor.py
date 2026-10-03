"""Make the seats editable.

A dossier you can't correct is a dossier you'll stop trusting. Two rules,
both learned expensively:

- **Retire, never delete.** Deleting a doctrine entry frees its id for reuse,
  and a later entry inheriting `D3` silently re-points every stored citation
  at *different content*. That is a wrong attribution, not a broken link —
  far worse. Retiring keeps the id spoken for forever.

- **Never let the user edit verification state.** The server decides it. If
  the user changes an entry's substance, it drops to `user` automatically,
  because the fact-check no longer covers what it now says. Otherwise the
  editor becomes a way to stamp an unchecked claim as confirmed — the exact
  laundering this design exists to prevent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from .dossier import DoctrineEntry

if TYPE_CHECKING:
    from .dossier import Dossier


@dataclass
class EditResult:
    """The result of an edit operation."""

    ok: bool
    message: str
    dossier: "Dossier | None" = None


def retire_entry(dossier: "Dossier", entry_id: str) -> EditResult:
    """Retire a doctrine entry. The id stays spoken for forever.

    Retiring keeps the id in the file but marks it as retired, so stored
    citations to that id remain valid (they point to the same content).
    Deleting would free the id for reuse, and a later entry inheriting `D3`
    would silently re-point every stored citation at different content.
    """
    for index, entry in enumerate(dossier.doctrine):
        if entry.id == entry_id:
            # Mark as retired by prefixing the text. The id stays spoken for
            # forever — stored citations to this id remain valid.
            dossier.doctrine[index] = replace(entry, text=f"[RETIRED] {entry.text}")
            return EditResult(
                ok=True,
                message=f"Entry {entry_id} retired. The id stays spoken for forever.",
                dossier=dossier,
            )

    return EditResult(
        ok=False,
        message=f"Entry {entry_id} not found in {dossier.name}'s dossier.",
    )


def edit_entry_text(
    dossier: "Dossier",
    entry_id: str,
    new_text: str,
) -> EditResult:
    """Edit a doctrine entry's text.

    If the user changes an entry's substance, it drops to `user`
    automatically, because the fact-check no longer covers what it now says.
    """
    for index, entry in enumerate(dossier.doctrine):
        if entry.id == entry_id:
            # Check if the text actually changed
            if entry.text == new_text:
                return EditResult(
                    ok=False,
                    message="No changes to save.",
                    dossier=dossier,
                )

            # Update the text and drop verification to "user" — the fact-check
            # no longer covers what the entry now says
            dossier.doctrine[index] = replace(entry, text=new_text, verification="user")

            return EditResult(
                ok=True,
                message=f"Entry {entry_id} updated. Verification dropped to 'user' — the fact-check no longer covers the new text.",
                dossier=dossier,
            )

    return EditResult(
        ok=False,
        message=f"Entry {entry_id} not found in {dossier.name}'s dossier.",
    )


def edit_entry_source(
    dossier: "Dossier",
    entry_id: str,
    new_source: str,
) -> EditResult:
    """Edit a doctrine entry's source.

    Changing the source also drops verification to "user", because the
    fact-check covered the old source, not the new one.
    """
    for index, entry in enumerate(dossier.doctrine):
        if entry.id == entry_id:
            if entry.source == new_source:
                return EditResult(
                    ok=False,
                    message="No changes to save.",
                    dossier=dossier,
                )

            dossier.doctrine[index] = replace(entry, source=new_source, verification="user")

            return EditResult(
                ok=True,
                message=f"Entry {entry_id} source updated. Verification dropped to 'user'.",
                dossier=dossier,
            )

    return EditResult(
        ok=False,
        message=f"Entry {entry_id} not found in {dossier.name}'s dossier.",
    )


def add_entry(
    dossier: "Dossier",
    text: str,
    source: str,
) -> EditResult:
    """Add a new doctrine entry.

    New entries are marked as "user" — they haven't been through the
    adversarial fact-check. The server decides verification state, never
    the user.
    """
    # Find the next available id
    existing_ids = {entry.id for entry in dossier.doctrine}
    next_num = 1
    while f"D{next_num}" in existing_ids:
        next_num += 1

    new_entry = DoctrineEntry(
        id=f"D{next_num}",
        text=text,
        source=source,
        verification="user",
    )

    dossier.doctrine.append(new_entry)

    return EditResult(
        ok=True,
        message=f"Entry D{next_num} added. Marked as 'user' — run the fact-check to verify.",
        dossier=dossier,
    )


def save_dossier(dossier: "Dossier", path: Path) -> EditResult:
    """Save a dossier back to its markdown file.

    The file is rewritten from the parsed dossier, so the format is
    always consistent. The user edits through the API, not by hand-editing
    the file.
    """
    try:
        path.write_text(_render_dossier(dossier), encoding="utf-8")
        return EditResult(
            ok=True,
            message=f"Saved {dossier.name}'s dossier.",
            dossier=dossier,
        )
    except OSError as exc:
        return EditResult(
            ok=False,
            message=f"Could not save: {exc}",
        )


def _render_dossier(dossier: "Dossier") -> str:
    """Render a dossier back to markdown.

    The format is always consistent because the file is rewritten from
    the parsed dossier, not hand-edited.
    """
    lines = [
        "---",
        f"id: {dossier.id}",
        f"name: {dossier.name}",
        f"seat_title: {dossier.seat_title}",
        f"domains: {', '.join(dossier.domains)}",
        f"status: {dossier.status}",
        "---",
        "",
        f"# {dossier.name} — {dossier.seat_title}",
        "",
        "## Doctrine",
        "",
    ]

    for entry in dossier.doctrine:
        lines.append(f"### {entry.id}")
        if entry.verification == "user":
            lines.append(f"[user] {entry.text}")
        else:
            lines.append(entry.text)
        lines.append(f"Source: {entry.source}")
        lines.append("")

    if dossier.objection:
        lines.extend([
            "## Characteristic objection",
            "",
            dossier.objection,
            "",
        ])

    if dossier.blind_spots:
        lines.extend([
            "## Blind spots",
            "",
        ])
        for spot in dossier.blind_spots:
            lines.append(f"- {spot}")
        lines.append("")

    if dossier.voice:
        lines.extend([
            "## Voice",
            "",
            dossier.voice,
            "",
        ])

    return "\n".join(lines)
