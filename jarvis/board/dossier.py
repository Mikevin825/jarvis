"""The dossier format and parser.

A dossier is a knowledge base, not a personality. Each seat is one markdown
file with numbered, sourced principles that a model reads and reasons from.

The parser reads one markdown file and returns a structured seat, or nothing.
It must reject, with a logged reason: a file with no domains, a file with no
doctrine, and a file with duplicate doctrine ids.

Doctrine ids are explicit in the file, not derived from ordering. Reordering
entries must never silently invalidate the citations on meetings already
stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DoctrineEntry:
    """One numbered principle with a source."""

    id: str  # e.g. "D1"
    text: str
    source: str
    verification: str = "sourced"  # "sourced" or "user"


@dataclass
class Dossier:
    """A seat's dossier — the knowledge base the model reasons from."""

    id: str
    name: str
    seat_title: str
    domains: list[str]
    status: str = "active"
    doctrine: list[DoctrineEntry] = field(default_factory=list)
    objection: str = ""
    blind_spots: list[str] = field(default_factory=list)
    voice: str = ""

    @property
    def doctrine_ids(self) -> set[str]:
        """The set of valid citation ids for this seat."""
        return {entry.id for entry in self.doctrine}

    def to_prompt(self) -> str:
        """Render the dossier as a system prompt for the seat's model call.

        This is the only context the seat receives. It doesn't know who else
        is in the room.
        """
        lines = [
            f"# {self.name} — {self.seat_title}",
            "",
            f"Domains: {', '.join(self.domains)}",
            "",
            "## Doctrine",
            "",
        ]
        for entry in self.doctrine:
            lines.append(f"### {entry.id}")
            lines.append(entry.text)
            lines.append(f"Source: {entry.source}")
            lines.append("")
        if self.objection:
            lines.append("## Characteristic objection")
            lines.append(self.objection)
            lines.append("")
        if self.blind_spots:
            lines.append("## Blind spots")
            for spot in self.blind_spots:
                lines.append(f"- {spot}")
            lines.append("")
        if self.voice:
            lines.append("## Voice")
            lines.append(self.voice)
            lines.append("")
        return "\n".join(lines)


class DossierError(Exception):
    """A dossier failed to parse."""


def parse_dossier(path: Path) -> Dossier | None:
    """Parse one markdown file into a Dossier.

    Returns None if the file is missing or unreadable. Raises DossierError
    if the file exists but is malformed (no domains, no doctrine, duplicate
    ids).

    Read files as UTF-8 tolerantly. A file saved in the wrong encoding should
    degrade to a logged warning, not an exception that takes out the roster.
    """
    if not path.exists():
        return None

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="latin-1")
        except Exception:  # noqa: BLE001
            return None
    except OSError:
        return None

    # Parse frontmatter
    frontmatter = _parse_frontmatter(text)
    if not frontmatter:
        raise DossierError(f"{path.name}: no frontmatter found")

    name = frontmatter.get("name", "").strip()
    if not name:
        raise DossierError(f"{path.name}: no name in frontmatter")

    domains = _parse_domains(frontmatter.get("domains", ""))
    if not domains:
        raise DossierError(f"{path.name}: no domains — could never be routed to")

    seat_title = frontmatter.get("seat_title", "").strip()
    status = frontmatter.get("status", "active").strip()

    # Parse doctrine entries
    doctrine = _parse_doctrine(text)
    if not doctrine:
        raise DossierError(f"{path.name}: no doctrine — nothing to cite")

    # Check for duplicate ids
    ids = [entry.id for entry in doctrine]
    if len(ids) != len(set(ids)):
        duplicates = sorted({id_ for id_ in ids if ids.count(id_) > 1})
        raise DossierError(
            f"{path.name}: duplicate doctrine ids: {', '.join(duplicates)}"
        )

    # Parse objection, blind spots, voice
    objection = _parse_section(text, "Characteristic objection")
    blind_spots = _parse_list_section(text, "Blind spots")
    voice = _parse_section(text, "Voice")

    return Dossier(
        id=frontmatter.get("id", path.stem),
        name=name,
        seat_title=seat_title,
        domains=domains,
        status=status,
        doctrine=doctrine,
        objection=objection,
        blind_spots=blind_spots,
        voice=voice,
    )


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Parse YAML-like frontmatter from markdown."""
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    result = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _parse_domains(raw: str) -> list[str]:
    """Parse a comma-separated list of domains."""
    return [d.strip() for d in raw.split(",") if d.strip()]


def _parse_doctrine(text: str) -> list[DoctrineEntry]:
    """Parse numbered doctrine entries from markdown.

    Each entry starts with ### D1, ### D2, etc. and contains text and a
    Source: line.
    """
    entries = []
    # Match ### D1 ... ### D2 or end of file
    pattern = re.compile(
        r"^###\s+(D\d+)\s*\n(.*?)(?=^###\s+D\d+\s*\n|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        entry_id = match.group(1)
        body = match.group(2).strip()

        # Extract source
        source_match = re.search(r"^Source:\s*(.+)$", body, re.MULTILINE)
        source = source_match.group(1).strip() if source_match else ""

        # Remove source line from text
        text_without_source = re.sub(
            r"^Source:\s*.+$", "", body, flags=re.MULTILINE
        ).strip()

        # Check for verification state
        verification = "sourced"
        if text_without_source.startswith("[user]"):
            verification = "user"
            text_without_source = text_without_source[6:].strip()

        entries.append(
            DoctrineEntry(
                id=entry_id,
                text=text_without_source,
                source=source,
                verification=verification,
            )
        )
    return entries


def _parse_section(text: str, heading: str) -> str:
    """Parse a section by heading, returning its body."""
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _parse_list_section(text: str, heading: str) -> list[str]:
    """Parse a section containing a bullet list."""
    body = _parse_section(text, heading)
    if not body:
        return []
    return [line.strip("- ").strip() for line in body.splitlines() if line.strip().startswith("-")]
