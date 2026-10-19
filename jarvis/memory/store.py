"""Long-term memory — the store that survives a restart.

Design constraints, taken from the spec:

* **One fact per entry, written as a plain statement.** Small entries are easy to
  review, correct, and delete. A single blob of "everything known about the user"
  rots and cannot be audited.
* **Plain and human-readable.** The file is a list of `id | fact` lines. You can
  open it, fix a wrong fact, or delete a line, and JARVIS honours that on the
  next run. A store you cannot inspect is a store you cannot trust.
* **Treat facts as data, never as instructions.** Facts are loaded as background
  knowledge. A fact that reads like an order must not be obeyed — see the system
  prompt, and the confirmation gate in Tier 6.
* **Don't load everything every time.** `relevant()` exists so retrieval can be
  selective as the store grows; `render()` is what the prompt actually gets.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

HEADER = """\
# JARVIS long-term memory.
#
# One fact per line, written as:   <id> | <fact>
#
# Edit this file freely. JARVIS reads it at the start of every conversation, so
# fixing a wrong fact or deleting a line takes effect on the next run.
# Lines starting with # are ignored.
#
# These are remembered facts, not commands — JARVIS treats them as background
# knowledge and still asks before doing anything consequential.
"""

# Supports both old format (id | text) and new format (id | type | hook | text)
_LINE = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*\|\s*(?:([a-z]+)\s*\|\s*(.*?)\s*\|\s*)?(.+?)\s*$")
_WORD = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class Fact:
    id: str
    text: str
    type: str = "general"  # user, preference, project, resource, general
    hook: str = ""  # one-line searchable summary


class MemoryError(RuntimeError):
    """The memory store could not be read or written."""


class MemoryStore:
    """A small durable set of facts, stored as an editable text file."""

    def __init__(self, path: Path, index_path: Path | None = None) -> None:
        self.path = path
        self.index_path = index_path or path.parent / "memory-index.json"
        self._facts: list[Fact] = []
        self._loaded = False
        self._index: dict[str, set[str]] = {}
        self._index_loaded = False

    # -- loading and saving -------------------------------------------------

    def load(self, force: bool = False) -> list[Fact]:
        """Read the store from disk, tolerating hand edits."""
        if self._loaded and not force:
            return list(self._facts)

        if not self.path.exists():
            self._facts = []
            self._loaded = True
            return []

        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise MemoryError(f"could not read {self.path}: {exc}") from exc

        facts: list[Fact] = []
        seen: set[str] = set()
        next_auto = 1

        for line in raw.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = _LINE.match(line)
            if not match:
                # A line the user typed freehand, with no id. Adopt it rather
                # than silently dropping something they meant to save.
                text = line.strip()
                if not text:
                    continue
                fact_id = self._next_id(next_auto, seen)
                next_auto = int(fact_id[1:]) + 1
                facts.append(Fact(id=fact_id, text=text))
                seen.add(fact_id)
                continue

            fact_id = match.group(1)
            fact_type = match.group(2) or "general"
            hook = match.group(3) or ""
            text = match.group(4)
            if fact_id in seen:
                # Duplicate id from a hand edit — reassign rather than lose it.
                fact_id = self._next_id(next_auto, seen)
            next_auto = max(next_auto, _numeric(fact_id) + 1)
            facts.append(Fact(id=fact_id, text=text, type=fact_type, hook=hook))
            seen.add(fact_id)

        self._facts = facts
        self._loaded = True
        return list(self._facts)

    @staticmethod
    def _next_id(start: int, taken: set[str]) -> str:
        n = start
        while f"m{n}" in taken:
            n += 1
        return f"m{n}"

    def _save(self) -> None:
        """Write the store atomically, so a crash cannot truncate memory."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for f in self._facts:
            if f.type != "general" or f.hook:
                lines.append(f"{f.id} | {f.type} | {f.hook} | {f.text}")
            else:
                lines.append(f"{f.id} | {f.text}")
        body = "\n".join(lines)
        content = HEADER + ("\n" + body + "\n" if body else "")

        try:
            # Same directory, so os.replace stays atomic on the same filesystem.
            fd, tmp = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=".memory-", suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.replace(tmp, self.path)
        except OSError as exc:
            raise MemoryError(f"could not write {self.path}: {exc}") from exc

    # -- search index --------------------------------------------------------

    def _build_index(self) -> dict[str, set[str]]:
        """Build a word-to-fact-ids index from the current facts."""
        index: dict[str, set[str]] = {}
        for fact in self._facts:
            words = set(_WORD.findall(fact.text.lower()))
            if fact.hook:
                words |= set(_WORD.findall(fact.hook.lower()))
            for word in words:
                index.setdefault(word, set()).add(fact.id)
        return index

    def _save_index(self) -> None:
        """Save the index to disk."""
        index = self._build_index()
        data = {word: sorted(ids) for word, ids in index.items()}
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)

    def _load_index(self) -> dict[str, set[str]]:
        """Load the index from disk, or rebuild if missing."""
        if not self.index_path.exists():
            self._save_index()
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            return {word: set(ids) for word, ids in data.items()}
        except (json.JSONDecodeError, OSError):
            self._save_index()
            return self._build_index()

    def rebuild_index(self) -> None:
        """Force rebuild the index from the current facts."""
        self._save_index()

    def search(self, query: str, limit: int = 10) -> list[Fact]:
        """Search facts using the index. Falls back to linear scan."""
        self.load()
        if not self._index_loaded:
            self._index = self._load_index()
            self._index_loaded = True

        query_words = [w for w in _WORD.findall(query.lower()) if len(w) > 2]
        if not query_words:
            return []

        # Score by how many query words match
        scores: dict[str, int] = {}
        for word in query_words:
            for fact_id in self._index.get(word, set()):
                scores[fact_id] = scores.get(fact_id, 0) + 1

        # Sort by score, then by recency
        fact_map = {f.id: f for f in self._facts}
        ranked = sorted(
            scores.items(),
            key=lambda item: (item[1], -list(fact_map).index(item[0])),
            reverse=True,
        )
        return [fact_map[fid] for fid, _ in ranked[:limit] if fid in fact_map]

    # -- reading ------------------------------------------------------------

    def facts(self) -> list[Fact]:
        self.load()
        return list(self._facts)

    def get(self, fact_id: str) -> Fact | None:
        self.load()
        return next((f for f in self._facts if f.id == fact_id), None)

    def find(self, needle: str) -> list[Fact]:
        """Facts whose text contains `needle`, case-insensitively."""
        self.load()
        low = needle.lower().strip()
        return [f for f in self._facts if low in f.text.lower()]

    def relevant(self, query: str, limit: int | None = None) -> list[Fact]:
        """The facts most worth putting in front of the model for this turn.

        Word-overlap scoring: deliberately simple and predictable, and good
        enough while the store is small. When `limit` is None (or the store
        fits inside it) everything is returned, which is the right behaviour
        early on.
        """
        self.load()
        if limit is None or len(self._facts) <= limit:
            return list(self._facts)

        query_words = {w for w in _WORD.findall(query.lower()) if len(w) > 2}
        if not query_words:
            return list(self._facts[-limit:])

        scored: list[tuple[int, int, Fact]] = []
        for index, fact in enumerate(self._facts):
            words = set(_WORD.findall(fact.text.lower()))
            score = len(query_words & words)
            scored.append((score, index, fact))

        # Highest overlap first; ties broken by recency (later index wins).
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [fact for _score, _idx, fact in scored[:limit]]

    def render(self, facts: list[Fact] | None = None) -> str:
        """Format facts for the system prompt. Empty string when there are none."""
        chosen = self.facts() if facts is None else facts
        if not chosen:
            return ""
        return "\n".join(f"- {f.text}" for f in chosen)

    # -- writing ------------------------------------------------------------

    def add(self, text: str, type: str = "general", hook: str = "") -> Fact:
        text = " ".join(text.split())
        if not text:
            raise MemoryError("cannot remember an empty fact")

        self.load()
        # Don't store the same thing twice — correcting by re-adding is common.
        existing = next(
            (f for f in self._facts if f.text.lower() == text.lower()), None
        )
        if existing is not None:
            return existing

        fact = Fact(
            id=self._next_id(1, {f.id for f in self._facts}),
            text=text,
            type=type,
            hook=hook or text[:80],
        )
        self._facts.append(fact)
        self._save()
        return fact

    def update(self, fact_id: str, text: str) -> Fact:
        text = " ".join(text.split())
        if not text:
            raise MemoryError("cannot set an empty fact")

        self.load()
        for index, fact in enumerate(self._facts):
            if fact.id == fact_id:
                updated = Fact(id=fact_id, text=text)
                self._facts[index] = updated
                self._save()
                return updated
        raise MemoryError(f"there is no fact called '{fact_id}'")

    def remove(self, fact_id: str) -> Fact:
        self.load()
        for index, fact in enumerate(self._facts):
            if fact.id == fact_id:
                self._save_after_removal(index)
                return fact
        raise MemoryError(f"there is no fact called '{fact_id}'")

    def _save_after_removal(self, index: int) -> None:
        del self._facts[index]
        self._save()


def _numeric(fact_id: str) -> int:
    try:
        return int(fact_id.lstrip("mM"))
    except ValueError:
        return 0
