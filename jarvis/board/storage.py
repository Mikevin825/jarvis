"""Store every meeting.

Question, seats, opinions, synthesis, cost. When surfacing the meeting card,
snapshot each cited entry's title and source into it. Then a stored meeting
renders its own citations without re-reading the dossier, and stays readable
after the file changes.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from ..paths import STATE_DIR

MEETINGS_FILE = STATE_DIR / "board-meetings.json"

if TYPE_CHECKING:
    from .chair import ChairSynthesis
    from .meeting import SeatOpinion


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
    """A stored meeting with all data needed to render it later."""

    id: str
    question: str
    opinions: list[StoredOpinion] = field(default_factory=list)
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
                    verification=c.get("verification", "sourced"),
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

    def store(
        self,
        question: str,
        opinions: list["SeatOpinion"],
        synthesis: "ChairSynthesis",
        dossiers: dict,
        total_cost_usd: float = 0.0,
        total_wall_clock_s: float = 0.0,
    ) -> StoredMeeting:
        """Store a meeting, snapshotting citations.

        Snapshot each cited entry's title and source into the stored meeting.
        Then a stored meeting renders its own citations without re-reading the
        dossier, and stays readable after the file changes.
        """
        if not self._loaded:
            self.load()

        stored_opinions = []
        for opinion in opinions:
            stored_citations = []
            for citation_id in opinion.citations:
                dossier = dossiers.get(opinion.seat_id)
                if dossier is None:
                    continue
                for entry in dossier.doctrine:
                    if entry.id == citation_id:
                        stored_citations.append(
                            StoredCitation(
                                entry_id=entry.id,
                                title=entry.text[:60] + "..." if len(entry.text) > 60 else entry.text,
                                source=entry.source,
                                verification=entry.verification,
                            )
                        )
                        break

            stored_opinions.append(
                StoredOpinion(
                    seat_id=opinion.seat_id,
                    seat_name=opinion.seat_name,
                    position=opinion.position,
                    reasoning=opinion.reasoning,
                    citations=stored_citations,
                    confidence=opinion.confidence,
                    would_change_mind=opinion.would_change_mind,
                    abstains=opinion.abstains,
                    unsourced=opinion.unsourced,
                    error=opinion.error,
                )
            )

        meeting = StoredMeeting(
            id=f"meeting-{uuid.uuid4().hex[:8]}",
            question=question,
            opinions=stored_opinions,
            synthesis=synthesis.summary,
            spoken=synthesis.spoken,
            split=synthesis.split,
            agreement=synthesis.agreement,
            discounts=synthesis.discounts,
            unverified_flags=synthesis.unverified_flags,
            unanimous=synthesis.unanimous,
            abstentions=synthesis.abstentions,
            total_cost_usd=total_cost_usd,
            total_wall_clock_s=total_wall_clock_s,
        )

        self._meetings.append(meeting)
        self._save()
        return meeting

    def all(self) -> list[StoredMeeting]:
        if not self._loaded:
            self.load()
        return list(self._meetings)

    def recent(self, count: int = 10) -> list[StoredMeeting]:
        """Most recent meetings, newest first."""
        return sorted(self.all(), key=lambda m: m.created_at, reverse=True)[:count]

    def get(self, meeting_id: str) -> StoredMeeting | None:
        for meeting in self.all():
            if meeting.id == meeting_id:
                return meeting
        return None
