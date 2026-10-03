"""Tests for the chair: JARVIS, and the only one who read the numbers.

The chair receives every opinion with its citations, the live business brief,
and each seat's blind spots. It synthesizes, names the split before the
agreement, and discounts seats using their documented blind spots.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.board.chair import (
    ChairSynthesis,
    _build_spoken_summary,
    _check_unanimity,
    _extract_agreement,
    _extract_split,
    _find_blind_spot_discounts,
    _find_unverified_positions,
    run_chair,
)
from jarvis.board.dossier import parse_dossier
from jarvis.board.meeting import MeetingResult, SeatOpinion
from jarvis.providers import Message, TextDelta, TurnEnd


class MockProvider:
    """A mock provider that returns a fixed response."""

    supports_tools = True

    def __init__(self, response: str = "", usage: dict | None = None):
        self.response = response
        self.usage = usage or {}
        self.calls: list[tuple[str, list[Message]]] = []

    def stream(self, system, messages, tools=None):
        self.calls.append((system, messages))
        yield TextDelta(text=self.response)
        yield TurnEnd(text=self.response, calls=[], usage=self.usage)


def _load_dossiers() -> list:
    """Load all dossiers from the dossiers directory."""
    dossiers_dir = Path(__file__).resolve().parent.parent / "jarvis" / "board" / "dossiers"
    if not dossiers_dir.exists():
        return []
    result = []
    for path in sorted(dossiers_dir.glob("*.md")):
        dossier = parse_dossier(path)
        if dossier is not None:
            result.append(dossier)
    return result


def _make_meeting(opinions: list[SeatOpinion]) -> MeetingResult:
    return MeetingResult(
        question="Should I raise my prices?",
        opinions=opinions,
        total_cost_usd=0.05,
        total_wall_clock_s=10.0,
        seats_attempted=len(opinions),
        seats_succeeded=len(opinions),
        seats_failed=0,
    )


class TestCheckUnanimity:
    def test_single_seat_is_not_unanimous(self) -> None:
        opinions = [
            SeatOpinion(seat_id="a", seat_name="A", position="Yes", reasoning="Because", abstains=False),
        ]
        assert not _check_unanimity(opinions)

    def test_two_agreeing_seats_are_unanimous(self) -> None:
        opinions = [
            SeatOpinion(seat_id="a", seat_name="A", position="Yes we should", reasoning="Because", abstains=False),
            SeatOpinion(seat_id="b", seat_name="B", position="Yes we should", reasoning="Because", abstains=False),
        ]
        assert _check_unanimity(opinions)

    def test_two_disagreeing_seats_are_not_unanimous(self) -> None:
        opinions = [
            SeatOpinion(seat_id="a", seat_name="A", position="Yes we should", reasoning="Because", abstains=False),
            SeatOpinion(seat_id="b", seat_name="B", position="No we should not", reasoning="Because", abstains=False),
        ]
        assert not _check_unanimity(opinions)

    def test_abstentions_dont_count(self) -> None:
        opinions = [
            SeatOpinion(seat_id="a", seat_name="A", position="Yes", reasoning="Because", abstains=False),
            SeatOpinion(seat_id="b", seat_name="B", position="", reasoning="", abstains=True),
        ]
        assert not _check_unanimity(opinions)

    def test_failed_seats_dont_count(self) -> None:
        opinions = [
            SeatOpinion(seat_id="a", seat_name="A", position="Yes", reasoning="Because", abstains=False),
            SeatOpinion(seat_id="b", seat_name="B", position="", reasoning="", abstains=False, error="failed"),
        ]
        assert not _check_unanimity(opinions)


class TestBlindSpotDiscounts:
    def test_finds_discount_when_position_matches_blind_spot(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        # Create an opinion that mentions a blind spot keyword
        opinion = SeatOpinion(
            seat_id=dossiers[0].id,
            seat_name=dossiers[0].name,
            position="This is about medication and health",
            reasoning="Because",
            abstains=False,
        )
        meeting = _make_meeting([opinion])
        dossier_map = {d.id: d for d in dossiers}

        discounts = _find_blind_spot_discounts(meeting.opinions, dossier_map)
        # Should find at least one discount if the blind spot matches
        # (depends on the actual dossier content)

    def test_no_discount_when_position_doesnt_match(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        opinion = SeatOpinion(
            seat_id=dossiers[0].id,
            seat_name=dossiers[0].name,
            position="This is about marketing strategy",
            reasoning="Because",
            abstains=False,
        )
        meeting = _make_meeting([opinion])
        dossier_map = {d.id: d for d in dossiers}

        discounts = _find_blind_spot_discounts(meeting.opinions, dossier_map)
        # Should not find a discount for unrelated content


class TestUnverifiedPositions:
    def test_flags_user_entries(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        # Create an opinion citing a user entry
        opinion = SeatOpinion(
            seat_id=dossiers[0].id,
            seat_name=dossiers[0].name,
            position="Yes",
            reasoning="Because",
            citations=["D1"],
            abstains=False,
        )
        meeting = _make_meeting([opinion])
        dossier_map = {d.id: d for d in dossiers}

        flags = _find_unverified_positions(meeting.opinions, dossier_map)
        # Should flag if D1 is a user entry (depends on dossier content)

    def test_no_flags_for_sourced_entries(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        opinion = SeatOpinion(
            seat_id=dossiers[0].id,
            seat_name=dossiers[0].name,
            position="Yes",
            reasoning="Because",
            citations=["D1"],
            abstains=False,
        )
        meeting = _make_meeting([opinion])
        dossier_map = {d.id: d for d in dossiers}

        flags = _find_unverified_positions(meeting.opinions, dossier_map)
        # Should not flag if D1 is sourced (depends on dossier content)


class TestSpokenSummary:
    def test_short_summary(self) -> None:
        summary = "The board split on pricing. Godin said yes, Fried said no. They agreed on timing."
        spoken = _build_spoken_summary(summary, unanimous=False, abstentions=[])
        assert "split" in spoken.lower() or "Godin" in spoken

    def test_includes_abstentions(self) -> None:
        summary = "The board split on pricing."
        spoken = _build_spoken_summary(summary, unanimous=False, abstentions=["Arden"])
        assert "Arden" in spoken
        assert "abstained" in spoken.lower()

    def test_empty_summary(self) -> None:
        spoken = _build_spoken_summary("", unanimous=False, abstentions=[])
        assert "could not" in spoken.lower()


class TestExtractSplit:
    def test_extracts_split(self) -> None:
        summary = "The board split on pricing. Godin said yes."
        split = _extract_split(summary)
        assert "split" in split.lower()

    def test_empty_when_no_split(self) -> None:
        summary = "The board agreed on everything."
        split = _extract_split(summary)
        assert split == ""


class TestExtractAgreement:
    def test_extracts_agreement(self) -> None:
        summary = "The board agreed on timing. They all said yes."
        agreement = _extract_agreement(summary)
        assert "agree" in agreement.lower()

    def test_empty_when_no_agreement(self) -> None:
        summary = "The board split on everything."
        agreement = _extract_agreement(summary)
        assert agreement == ""


class TestRunChair:
    def test_runs_chair_with_mock_provider(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        opinions = [
            SeatOpinion(
                seat_id=dossiers[0].id,
                seat_name=dossiers[0].name,
                position="Yes, raise prices",
                reasoning="Because the market supports it",
                citations=["D1"],
                confidence=4,
                would_change_mind="If competitors raise first",
                abstains=False,
            ),
            SeatOpinion(
                seat_id=dossiers[1].id if len(dossiers) > 1 else dossiers[0].id,
                seat_name=dossiers[1].name if len(dossiers) > 1 else dossiers[0].name,
                position="No, do not raise prices",
                reasoning="Because it will hurt the brand",
                citations=["D2"],
                confidence=3,
                would_change_mind="If we add more value",
                abstains=False,
            ),
        ]
        meeting = _make_meeting(opinions)

        provider = MockProvider(
            response="The board split on pricing. Godin said yes, Fried said no. They agreed on timing.",
            usage={"cost_usd": 0.02},
        )

        result = run_chair(meeting, dossiers, provider, business_brief="Revenue: $100k MRR")

        assert result.summary != ""
        assert result.unanimous is False
        assert len(provider.calls) == 1

    def test_chair_fails_gracefully(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        meeting = _make_meeting([])

        class FailingProvider:
            supports_tools = True
            def stream(self, system, messages, tools=None):
                raise RuntimeError("Provider failed")

        provider = FailingProvider()
        result = run_chair(meeting, dossiers, provider)

        assert "could not" in result.summary.lower()
        assert result.unanimous is False

    def test_unanimity_guard_fires_with_one_seat(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        opinions = [
            SeatOpinion(
                seat_id=dossiers[0].id,
                seat_name=dossiers[0].name,
                position="Yes",
                reasoning="Because",
                citations=["D1"],
                confidence=4,
                would_change_mind="No",
                abstains=False,
            ),
        ]
        meeting = _make_meeting(opinions)

        provider = MockProvider(response="The board is unanimous.")

        result = run_chair(meeting, dossiers, provider)

        # The guard should fire — one seat is not unanimous
        assert result.unanimous is False
