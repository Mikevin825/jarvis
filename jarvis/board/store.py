"""Store every meeting.

Question, seats, opinions, synthesis, cost. When you surface the meeting card,
snapshot each cited entry's title and source into it. Then a stored meeting
renders its own citations without re-reading the dossier, and stays readable
after the file changes.

Retire, never delete. Deleting a doctrine entry frees its id for reuse, and a
later entry inheriting D3 silently re-points every stored citation at
different content. That is a wrong attribution, not a broken link — far worse.
Retiring keeps the id spoken for forever.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from ..paths import STATE_DIR

MEETINGS_FILE = STATE_DIR / "board-meetings.json"


@dataclass
class StoredCitation:
    """A snapshot of a cited doctrine entry at meeting time."""

    entry_id: str
    title: str
    source: str
    verification: str


@dataclass
class StoredOpinion:
    """One seat's opinion, with citation snapshots."""

    seat_id: str
    seat_name: str
    position: str
    reasoning: str
    citations: list[StoredCitation] = field(default_factory=list)
    confidence: int = 3
    would_change_mind: str = ""
    abstains: bool = False
    unsourced: bool = False
    error: str | None = None


@dataclass
class StoredMeeting:
    """A stored meeting with all citation snapshots."""

    id: str
    question: str
    opinions: list[StoredOpinion] = field(default_factory=list)
    summary: str = ""
    synthesis: str = ""
    spoken: str = ""
    split: str = ""
    agreement: str = ""
    discounts: list[str] = field(default_factory=list)
    unverified_flags: list[str] = field(default_factory=list)
    unanimous: bool = False
    abstentions: list[str] = field(default_factory=list)
    total_cost_usd: float = 0.0
    total_wall_clock_s: float = 0.0
    seats_attempted: int = 0
    seats_succeeded: int = 0
    seats_failed: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "opinions": [
                {
                    "seat_id": o.seat_id,
                    "seat_name": o.seat_name,
                    "position": o.position,
                    "reasoning": o.reasoning,
                    "citations": [
                        {
                            "entry_id": c.entry_id,
                            "title": c.title,
                            "source": c.source,
                            "verification": c.verification,
                        }
                        for c in o.citations
                    ],
                    "confidence": o.confidence,
                    "would_change_mind": o.would_change_mind,
                    "abstains": o.abstains,
                    "unsourced": o.unsourced,
                    "error": o.error,
                }
                for o in self.opinions
            ],
            "summary": self.summary,
            "synthesis": self.synthesis,
            "spoken": self.spoken,
            "split": self.split,
            "agreement": self.agreement,
            "discounts": self.discounts,
            "unverified_flags": self.unverified_flags,
            "unanimous": self.unanimous,
            "abstentions": self.abstentions,
            "total_cost_usd": self.total_cost_usd,
            "total_wall_clock_s": self.total_wall_clock_s,
            "seats_attempted": self.seats_attempted,
            "seats_succeeded": self.seats_succeeded,
            "seats_failed": self.seats_failed,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "StoredMeeting":
        opinions = []
        for o in raw.get("opinions", []):
            citations = [
                StoredCitation(
                    entry_id=c.get("entry_id", ""),
                    title=c.get("title", ""),
                    source=c.get("source", ""),
                    verification=c.get("verification", "user"),
                )
                for c in o.get("citations", [])
            ]
            opinions.append(
                StoredOpinion(
                    seat_id=o.get("seat_id", ""),
                    seat_name=o.get("seat_name", ""),
                    position=o.get("position", ""),
                    reasoning=o.get("reasoning", ""),
                    citations=citations,
                    confidence=o.get("confidence", 3),
                    would_change_mind=o.get("would_change_mind", ""),
                    abstains=o.get("abstains", False),
                    unsourced=o.get("unsourced", False),
                    error=o.get("error"),
                )
            )

        created = raw.get("created_at", "")
        try:
            created_dt = datetime.fromisoformat(created) if created else datetime.now(timezone.utc)
        except (TypeError, ValueError):
            created_dt = datetime.now(timezone.utc)
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)

        return cls(
            id=raw.get("id", ""),
            question=raw.get("question", ""),
            opinions=opinions,
            summary=raw.get("summary", ""),
            synthesis=raw.get("synthesis", ""),
            spoken=raw.get("spoken", ""),
            split=raw.get("split", ""),
            agreement=raw.get("agreement", ""),
            discounts=raw.get("discounts", []),
            unverified_flags=raw.get("unverified_flags", []),
            unanimous=raw.get("unanimous", False),
            abstentions=raw.get("abstentions", []),
            total_cost_usd=raw.get("total_cost_usd", 0.0),
            total_wall_clock_s=raw.get("total_wall_clock_s", 0.0),
            seats_attempted=raw.get("seats_attempted", 0),
            seats_succeeded=raw.get("seats_succeeded", 0),
            seats_failed=raw.get("seats_failed", 0),
            created_at=created_dt,
        )


class MeetingStore:
    """A durable store of board meetings."""

    def __init__(self, path: Path = MEETINGS_FILE) -> None:
        self.path = path
        self._meetings: list[StoredMeeting] = []
        self._loaded = False

    def load(self) -> "MeetingStore":
        if not self.path.exists():
            self._loaded = True
            return self
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._loaded = True
            return self
        self._meetings = [StoredMeeting.from_dict(m) for m in raw.get("meetings", [])]
        self._loaded = True
        return self

    def _save(self) -> None:
        payload = {
            "meetings": [m.to_dict() for m in self._meetings],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    def store(self, meeting: StoredMeeting) -> None:
        """Store a meeting."""
        if not self._loaded:
            self.load()
        self._meetings.append(meeting)
        self._save()

    def all(self) -> list[StoredMeeting]:
        """All stored meetings, newest first."""
        if not self._loaded:
            self.load()
        return list(reversed(self._meetings))

    def get(self, meeting_id: str) -> StoredMeeting | None:
        """Get a meeting by id."""
        if not self._loaded:
            self.load()
        for m in self._meetings:
            if m.id == meeting_id:
                return m
        return None

    def count(self) -> int:
        """Number of stored meetings."""
        if not self._loaded:
            self.load()
        return len(self._meetings)
