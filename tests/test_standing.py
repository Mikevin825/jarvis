"""Tests for the standing review.

The most valuable thing a real board does is show up when you didn't call the
meeting. This check makes that happen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.board.dossier import parse_dossier
from jarvis.board.standing import (
    STANDING_REVIEW_PROMPT,
    StandingReviewCheck,
    StandingReviewResult,
    run_standing_review,
    to_stored_meeting,
)
from jarvis.providers import Message, TextDelta, TurnEnd


class MockProvider:
    """A mock provider that returns a fixed response."""

    supports_tools = True

    def __init__(self, response: str = "", usage: dict | None = None):
        self.response = response
        self.usage = usage or {}
        self.calls: list[tuple[str, list[Message]]] = []

    def stream(self, system, messages, tools=None, max_tokens=None):
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


class TestStandingReviewPrompt:
    def test_prompt_is_load_bearing(self) -> None:
        """The last line is load-bearing — without it the board hands the question back."""
        assert "Do not ask what they want to discuss" in STANDING_REVIEW_PROMPT
        assert "this is your agenda, not theirs" in STANDING_REVIEW_PROMPT

    def test_prompt_asks_for_numbers(self) -> None:
        assert "Read the numbers" in STANDING_REVIEW_PROMPT
        assert "specific number" in STANDING_REVIEW_PROMPT

    def test_prompt_asks_for_action(self) -> None:
        assert "one concrete thing to do" in STANDING_REVIEW_PROMPT
        assert "next 30 days" in STANDING_REVIEW_PROMPT


class TestRunStandingReview:
    def test_runs_with_mock_provider(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        response = '{"position": "Focus on retention", "reasoning": "Because churn is high", "citations": ["D1"], "confidence": 4, "would_change_mind": "If churn drops", "abstains": false}'
        provider = MockProvider(response=response, usage={"cost_usd": 0.01})

        result = run_standing_review(
            dossiers=dossiers,
            provider=provider,
            business_brief="MRR: $100k, Churn: 5%",
        )

        assert result.seats_attempted > 0
        assert result.total_cost_usd > 0
        assert len(provider.calls) > 0

    def test_uses_all_seats(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        response = '{"position": "Yes", "reasoning": "Because", "citations": ["D1"], "confidence": 4, "would_change_mind": "No", "abstains": false}'
        provider = MockProvider(response=response, usage={"cost_usd": 0.01})

        result = run_standing_review(
            dossiers=dossiers,
            provider=provider,
        )

        # Should attempt all seats
        assert result.seats_attempted == len(dossiers)


class TestToStoredMeeting:
    def test_converts_result(self) -> None:
        result = StandingReviewResult(
            question=STANDING_REVIEW_PROMPT,
            synthesis="The board recommends focusing on retention.",
            spoken="Focus on retention.",
            split="Godin said yes, Fried said no.",
            total_cost_usd=0.05,
            seats_attempted=4,
            seats_succeeded=4,
        )

        stored = to_stored_meeting(result)

        assert stored.id.startswith("standing-")
        assert stored.question == "Standing review — the business itself"
        assert stored.summary == "The board recommends focusing on retention."
        assert stored.spoken == "Focus on retention."
        assert stored.total_cost_usd == 0.05


class TestStandingReviewCheck:
    def test_name_is_correct(self) -> None:
        assert StandingReviewCheck.name == "board-standing-review"

    def test_returns_check_result(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        response = '{"position": "Focus on retention", "reasoning": "Because churn is high", "citations": ["D1"], "confidence": 4, "would_change_mind": "If churn drops", "abstains": false}'
        provider = MockProvider(response=response, usage={"cost_usd": 0.01})

        check = StandingReviewCheck(
            interval_seconds=2592000,  # 30 days
            settings={"business_brief": "MRR: $100k"},
            dossiers=dossiers,
            provider=provider,
        )

        from jarvis.heartbeat.checks import CheckContext

        result = check.run(CheckContext())
        assert result.surfaced
        assert "standing review" in result.summary
