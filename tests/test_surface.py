"""Tests for surfacing meetings in the inbox.

A meeting that finishes into a log file nobody reads is a meeting that didn't
happen. Surface it the way JARVIS already surfaces things — the inbox.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.board.store import StoredCitation, StoredMeeting, StoredOpinion
from jarvis.board.surface import surface_meeting, surface_meeting_card
from jarvis.heartbeat.inbox import Inbox


def _make_stored_meeting() -> StoredMeeting:
    return StoredMeeting(
        id="m1",
        question="Should I raise prices?",
        summary="The board split on pricing.",
        spoken="Godin said yes, Fried said no.",
        split="Godin said yes, Fried said no.",
        opinions=[
            StoredOpinion(
                seat_id="seth-godin",
                seat_name="Seth Godin",
                position="Yes, raise prices",
                reasoning="Because the market supports it",
                citations=[StoredCitation(entry_id="D1", title="Permission", source="Book", verification="sourced")],
                confidence=4,
                abstains=False,
            ),
            StoredOpinion(
                seat_id="jason-fried",
                seat_name="Jason Fried",
                position="No, do not raise prices",
                reasoning="Because it will hurt the brand",
                citations=[StoredCitation(entry_id="D2", title="Calm", source="Book", verification="sourced")],
                confidence=3,
                abstains=False,
            ),
        ],
        discounts=["Fried: position falls inside blind spot"],
        unverified_flags=[],
        unanimous=False,
        abstentions=[],
        total_cost_usd=0.05,
        total_wall_clock_s=10.0,
    )


class TestSurfaceMeeting:
    def test_creates_notice_in_inbox(self, tmp_path: Path) -> None:
        inbox = Inbox(tmp_path / "inbox.json")
        meeting = _make_stored_meeting()

        notice_id = surface_meeting(inbox, meeting)

        assert notice_id != ""
        assert inbox.count_pending() == 1

    def test_notice_contains_question(self, tmp_path: Path) -> None:
        inbox = Inbox(tmp_path / "inbox.json")
        meeting = _make_stored_meeting()

        surface_meeting(inbox, meeting)

        pending = inbox.pending()
        assert len(pending) == 1
        assert "Should I raise prices?" in pending[0].body

    def test_notice_contains_spoken_summary(self, tmp_path: Path) -> None:
        inbox = Inbox(tmp_path / "inbox.json")
        meeting = _make_stored_meeting()

        surface_meeting(inbox, meeting)

        pending = inbox.pending()
        assert "Godin said yes" in pending[0].body

    def test_notice_contains_citations(self, tmp_path: Path) -> None:
        inbox = Inbox(tmp_path / "inbox.json")
        meeting = _make_stored_meeting()

        surface_meeting(inbox, meeting)

        pending = inbox.pending()
        assert "D1" in pending[0].body
        assert "D2" in pending[0].body

    def test_notice_contains_cost(self, tmp_path: Path) -> None:
        inbox = Inbox(tmp_path / "inbox.json")
        meeting = _make_stored_meeting()

        surface_meeting(inbox, meeting)

        pending = inbox.pending()
        assert "$0.05" in pending[0].body


class TestSurfaceMeetingCard:
    def test_card_contains_all_fields(self) -> None:
        meeting = _make_stored_meeting()
        card = surface_meeting_card(None, meeting)

        assert card["id"] == "m1"
        assert card["question"] == "Should I raise prices?"
        assert card["summary"] == "The board split on pricing."
        assert card["spoken"] == "Godin said yes, Fried said no."
        assert len(card["opinions"]) == 2
        assert card["opinions"][0]["seat_name"] == "Seth Godin"
        assert card["opinions"][0]["citations"][0]["entry_id"] == "D1"
        assert card["total_cost_usd"] == 0.05

    def test_card_includes_discounts_and_flags(self) -> None:
        meeting = _make_stored_meeting()
        card = surface_meeting_card(None, meeting)

        assert len(card["discounts"]) == 1
        assert "Fried" in card["discounts"][0]
        assert card["unverified_flags"] == []
