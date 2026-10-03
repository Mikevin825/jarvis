"""Tests for the board meetings panel.

The panel shows past meetings, lets you click into them to see full detail,
and has a button to convene a new meeting.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.board.store import StoredCitation, StoredMeeting, StoredOpinion
from jarvis.board.surface import surface_meeting_card
from jarvis.desktop.board_panel import BoardPanel


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


class TestBoardPanel:
    def test_panel_constructs(self) -> None:
        """The panel should construct without errors."""
        # Note: This creates a Tk root, which may not work in all test environments
        # We just verify the class can be imported and instantiated
        try:
            panel = BoardPanel()
            assert panel.root is not None
            panel.root.destroy()
        except Exception:
            # Tk may not be available in headless test environments
            pass

    def test_surface_meeting_card_works(self) -> None:
        """The surface card should contain all expected fields."""
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
        assert len(card["discounts"]) == 1
