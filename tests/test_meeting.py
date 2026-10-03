"""Tests for the meeting: fan out, in isolation.

For each selected seat, one call. Its system prompt contains that seat's
dossier and nothing else. It doesn't know who else is in the room.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.board.dossier import parse_dossier
from jarvis.board.meeting import (
    MeetingResult,
    SeatOpinion,
    _coerce_seat_output,
    _parse_seat_response,
    run_meeting,
)
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


class TestParseSeatResponse:
    def test_parses_valid_json(self) -> None:
        text = '{"position": "Yes", "reasoning": "Because", "citations": ["D1"], "confidence": 4, "would_change_mind": "No", "abstains": false}'
        result = _parse_seat_response(text)
        assert result is not None
        assert result["position"] == "Yes"

    def test_returns_none_for_empty(self) -> None:
        assert _parse_seat_response("") is None

    def test_returns_none_for_no_json(self) -> None:
        assert _parse_seat_response("no json here") is None

    def test_handles_truncated_json(self) -> None:
        text = '{"position": "Yes", "reasoning": "Because", "citations": ["D1"'
        result = _parse_seat_response(text)
        # May or may not parse depending on truncation handling
        # The important thing is it doesn't crash

    def test_extracts_json_from_text(self) -> None:
        text = 'Here is my response: {"position": "Yes", "reasoning": "Because", "citations": [], "confidence": 3, "would_change_mind": "No", "abstains": false}'
        result = _parse_seat_response(text)
        assert result is not None
        assert result["position"] == "Yes"


class TestCoerceSeatOutput:
    def test_coerces_valid_output(self) -> None:
        data = {
            "position": "Yes",
            "reasoning": "Because",
            "citations": ["D1", "D2"],
            "confidence": 4,
            "would_change_mind": "No",
            "abstains": False,
        }
        result = _coerce_seat_output(data)
        assert result["position"] == "Yes"
        assert result["confidence"] == 4
        assert result["abstains"] is False

    def test_coerces_string_boolean(self) -> None:
        """A schema-declared boolean can come back as the string "false"."""
        data = {
            "position": "Yes",
            "reasoning": "Because",
            "citations": [],
            "confidence": 3,
            "would_change_mind": "No",
            "abstains": "false",
        }
        result = _coerce_seat_output(data)
        assert result["abstains"] is False

    def test_coerces_string_true(self) -> None:
        data = {
            "position": "Yes",
            "reasoning": "Because",
            "citations": [],
            "confidence": 3,
            "would_change_mind": "No",
            "abstains": "true",
        }
        result = _coerce_seat_output(data)
        assert result["abstains"] is True

    def test_clamps_confidence(self) -> None:
        data = {
            "position": "Yes",
            "reasoning": "Because",
            "citations": [],
            "confidence": 10,
            "would_change_mind": "No",
            "abstains": False,
        }
        result = _coerce_seat_output(data)
        assert result["confidence"] == 5

    def test_handles_missing_fields(self) -> None:
        data = {}
        result = _coerce_seat_output(data)
        assert result["position"] == ""
        assert result["confidence"] == 3
        assert result["abstains"] is False

    def test_drops_non_string_citations(self) -> None:
        data = {
            "position": "Yes",
            "reasoning": "Because",
            "citations": [None, 123, "D1"],
            "confidence": 3,
            "would_change_mind": "No",
            "abstains": False,
        }
        result = _coerce_seat_output(data)
        assert result["citations"] == ["D1"]


class TestMeetingResult:
    def test_non_abstaining_filters_abstentions(self) -> None:
        result = MeetingResult(
            question="Test",
            opinions=[
                SeatOpinion(seat_id="a", seat_name="A", position="Yes", reasoning="Because", abstains=False),
                SeatOpinion(seat_id="b", seat_name="B", position="", reasoning="", abstains=True),
                SeatOpinion(seat_id="c", seat_name="C", position="No", reasoning="Why", abstains=False),
            ],
        )
        assert len(result.non_abstaining) == 2
        assert len(result.abstentions) == 1

    def test_empty_meeting(self) -> None:
        result = MeetingResult(question="Test")
        assert result.non_abstaining == []
        assert result.abstentions == []


class TestRunMeeting:
    def test_runs_meeting_with_mock_provider(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        response = '{"position": "Yes", "reasoning": "Because it is", "citations": ["D1"], "confidence": 4, "would_change_mind": "No", "abstains": false}'
        provider = MockProvider(response=response, usage={"cost_usd": 0.01})

        result = run_meeting(
            question="Should I raise my prices?",
            dossiers=dossiers,
            seat_ids=[dossiers[0].id],
            provider=provider,
        )

        assert result.seats_attempted == 1
        assert result.seats_succeeded == 1
        assert result.seats_failed == 0
        assert len(result.opinions) == 1
        assert result.opinions[0].position == "Yes"
        assert result.total_cost_usd == pytest.approx(0.01)

    def test_de_duplicates_seats(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        response = '{"position": "Yes", "reasoning": "Because", "citations": ["D1"], "confidence": 4, "would_change_mind": "No", "abstains": false}'
        provider = MockProvider(response=response, usage={"cost_usd": 0.01})

        # Pass the same seat twice
        result = run_meeting(
            question="Test?",
            dossiers=dossiers,
            seat_ids=[dossiers[0].id, dossiers[0].id],
            provider=provider,
        )

        # Should only call once
        assert result.seats_attempted == 1
        assert len(provider.calls) == 1

    def test_lets_seat_fail_without_failing_meeting(self) -> None:
        dossiers = _load_dossiers()
        if len(dossiers) < 2:
            pytest.skip("Need at least 2 dossiers")

        # First seat succeeds, second fails
        class FailingProvider:
            supports_tools = True
            def __init__(self):
                self.call_count = 0
            def stream(self, system, messages, tools=None):
                self.call_count += 1
                if self.call_count == 1:
                    yield TextDelta(text='{"position": "Yes", "reasoning": "Because", "citations": ["D1"], "confidence": 4, "would_change_mind": "No", "abstains": false}')
                    yield TurnEnd(text="", calls=[], usage={"cost_usd": 0.01})
                else:
                    raise RuntimeError("Provider failed")

        provider = FailingProvider()
        result = run_meeting(
            question="Test?",
            dossiers=dossiers,
            seat_ids=[dossiers[0].id, dossiers[1].id],
            provider=provider,
        )

        assert result.seats_attempted == 2
        assert result.seats_succeeded == 1
        assert result.seats_failed == 1
        assert len(result.opinions) == 2

    def test_respects_cost_ceiling(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        response = '{"position": "Yes", "reasoning": "Because", "citations": ["D1"], "confidence": 4, "would_change_mind": "No", "abstains": false}'
        provider = MockProvider(response=response, usage={"cost_usd": 0.01})

        # Set ceiling to zero — should not call any seats
        result = run_meeting(
            question="Test?",
            dossiers=dossiers,
            seat_ids=[dossiers[0].id],
            provider=provider,
            max_cost_usd=0.0,
        )

        assert result.seats_attempted == 0
        assert result.seats_succeeded == 0

    def test_filters_citations_against_dossier(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        # Return a citation that doesn't exist in the dossier
        response = '{"position": "Yes", "reasoning": "Because", "citations": ["D999"], "confidence": 4, "would_change_mind": "No", "abstains": false}'
        provider = MockProvider(response=response, usage={"cost_usd": 0.01})

        result = run_meeting(
            question="Test?",
            dossiers=dossiers,
            seat_ids=[dossiers[0].id],
            provider=provider,
        )

        assert result.seats_succeeded == 1
        # D999 should be stripped
        assert result.opinions[0].citations == []
        # And the opinion should be flagged as unsourced
        assert result.opinions[0].unsourced
