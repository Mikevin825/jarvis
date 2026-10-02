"""The inbox — where a surfaced notice waits until you have seen it.

The single most common way a proactive feature silently fails is
deliver-once-and-lose-it: the assistant notices something while your interface is
closed or you are asleep, fires it into the void, and forgets. So notices are
written here first and only marked delivered once they have actually been shown.

Everything here is dismissible. An inbox you cannot empty becomes clutter you
learn to ignore.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# How much a notice is allowed to intrude.
QUIET = "quiet"      # only ever seen when you go looking
NORMAL = "normal"    # shown on return, held during quiet hours
URGENT = "urgent"    # may interrupt, even during quiet hours


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Notice:
    id: str
    source: str
    title: str
    body: str
    level: str = NORMAL
    created: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    delivered: bool = False
    dismissed: bool = False

    @property
    def urgent(self) -> bool:
        return self.level == URGENT

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "title": self.title,
            "body": self.body,
            "level": self.level,
            "created": _iso(self.created),
            "delivered": self.delivered,
            "dismissed": self.dismissed,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Notice":
        created = raw.get("created")
        try:
            when = datetime.fromisoformat(created) if created else datetime.now(timezone.utc)
        except (TypeError, ValueError):
            when = datetime.now(timezone.utc)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return cls(
            id=str(raw.get("id", "")),
            source=raw.get("source", "unknown"),
            title=raw.get("title", ""),
            body=raw.get("body", ""),
            level=raw.get("level", NORMAL),
            created=when,
            delivered=bool(raw.get("delivered", False)),
            dismissed=bool(raw.get("dismissed", False)),
        )


class Inbox:
    """A durable, dismissible queue of things worth telling the user."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._notices: list[Notice] = []
        self._next = 1
        self._loaded = False

    def load(self) -> "Inbox":
        if not self.path.exists():
            self._loaded = True
            return self
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A corrupt inbox must not stop the assistant from running; start
            # clean rather than crashing the heartbeat.
            self._loaded = True
            return self

        self._next = int(raw.get("next_id", 1))
        self._notices = [Notice.from_dict(n) for n in raw.get("notices", [])]
        self._loaded = True
        return self

    def _save(self) -> None:
        payload = {
            "next_id": self._next,
            "notices": [n.to_dict() for n in self._notices],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=".inbox-", suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            # Losing a notice is bad; crashing the heartbeat is worse.
            pass

    # -- writing ------------------------------------------------------------

    def add(
        self, *, source: str, title: str, body: str = "", level: str = NORMAL
    ) -> Notice:
        if not self._loaded:
            self.load()
        notice = Notice(
            id=f"n{self._next}",
            source=source,
            title=title,
            body=body,
            level=level,
        )
        self._next += 1
        self._notices.append(notice)
        self._save()
        return notice

    # -- reading ------------------------------------------------------------

    def all(self) -> list[Notice]:
        if not self._loaded:
            self.load()
        return list(self._notices)

    def pending(self) -> list[Notice]:
        """Undismissed notices, oldest first."""
        return [n for n in self.all() if not n.dismissed]

    def undelivered(self) -> list[Notice]:
        """Notices the user has not yet been shown — the catch-up set."""
        return [n for n in self.all() if not n.dismissed and not n.delivered]

    def count_pending(self) -> int:
        return len(self.pending())

    # -- updating -----------------------------------------------------------

    def mark_delivered(self, notice_id: str) -> None:
        for notice in self.all():
            if notice.id == notice_id:
                notice.delivered = True
        self._save()

    def mark_all_delivered(self) -> None:
        for notice in self.all():
            notice.delivered = True
        self._save()

    def dismiss(self, notice_id: str) -> bool:
        found = False
        for notice in self.all():
            if notice.id == notice_id:
                notice.dismissed = True
                notice.delivered = True
                found = True
        if found:
            self._save()
        return found

    def dismiss_all(self) -> int:
        count = 0
        for notice in self.all():
            if not notice.dismissed:
                notice.dismissed = True
                notice.delivered = True
                count += 1
        if count:
            self._save()
        return count

    def prune(self, keep_dismissed: int = 50) -> None:
        """Trim old dismissed notices so the file does not grow forever."""
        if not self._loaded:
            self.load()
        dismissed = [n for n in self._notices if n.dismissed]
        if len(dismissed) <= keep_dismissed:
            return
        keep = {n.id for n in dismissed[-keep_dismissed:]}
        self._notices = [
            n for n in self._notices if not n.dismissed or n.id in keep
        ]
        self._save()
