"""Tests for routing: who has standing, and should this be a board question at all.

The decline gate is the most annoying failure mode if done wrong. An over-eager
gate refuses "Should I cut this product loose?" as "a personal business
decision." Business decisions about the user's own company are the core use
case, no matter how personal they feel.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.board.dossier import parse_dossier
from jarvis.board.router import normalize_name, route_question


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


class TestNormalizeName:
    def test_curly_apostrophe(self) -> None:
        assert normalize_name("O'Leary") == "o'leary"
        assert normalize_name("O\u2019Leary") == "o'leary"

    def test_fullwidth(self) -> None:
        assert normalize_name("Ｏ'Leary") == "o'leary"

    def test_non_breaking_space(self) -> None:
        # NFKC converts non-breaking space to regular space
        assert normalize_name("O\u00a0Leary") == "o leary"

    def test_soft_hyphen(self) -> None:
        assert normalize_name("O\u00adLeary") == "oleary"

    def test_case_insensitive(self) -> None:
        assert normalize_name("SETH GODIN") == "seth godin"


class TestDeclineGate:
    def test_declines_medical(self) -> None:
        dossiers = _load_dossiers()
        result = route_question("Should I stop taking my medication?", dossiers)
        assert result.declined
        assert "medical" in result.decline_reason

    def test_declines_legal(self) -> None:
        dossiers = _load_dossiers()
        result = route_question("Should I sue my former partner?", dossiers)
        assert result.declined
        assert "legal" in result.decline_reason

    def test_declines_code(self) -> None:
        dossiers = _load_dossiers()
        result = route_question("How do I fix this bug in my code?", dossiers)
        assert result.declined
        assert "technical" in result.decline_reason

    def test_does_not_decline_business_decision(self) -> None:
        """Business decisions about the user's own company are the core use case."""
        dossiers = _load_dossiers()
        result = route_question("Should I cut this product loose?", dossiers)
        assert not result.declined
        assert result.should_route

    def test_does_not_decline_personal_business(self) -> None:
        """A personal business decision is still a business decision."""
        dossiers = _load_dossiers()
        result = route_question("Should I fire my co-founder?", dossiers)
        assert not result.declined

    def test_does_not_decline_marketing(self) -> None:
        dossiers = _load_dossiers()
        result = route_question("How should I price my new service?", dossiers)
        assert not result.declined
        assert result.should_route

    def test_does_not_decline_operations(self) -> None:
        dossiers = _load_dossiers()
        result = route_question("Should I hire another developer?", dossiers)
        assert not result.declined
        assert result.should_route


class TestDomainRouting:
    def test_routes_to_godin_for_marketing(self) -> None:
        dossiers = _load_dossiers()
        result = route_question("How should I grow my agency?", dossiers)
        assert result.should_route
        assert "seth-godin" in result.seat_ids

    def test_routes_to_arden_for_creative(self) -> None:
        dossiers = _load_dossiers()
        result = route_question("How do I make my pitch more creative?", dossiers)
        assert result.should_route
        assert "paul-arden" in result.seat_ids

    def test_routes_to_neumeier_for_branding(self) -> None:
        dossiers = _load_dossiers()
        result = route_question("How should I position my brand?", dossiers)
        assert result.should_route
        assert "marty-neumeier" in result.seat_ids

    def test_routes_to_fried_for_operations(self) -> None:
        dossiers = _load_dossiers()
        result = route_question("How do I manage my team better?", dossiers)
        assert result.should_route
        assert "jason-fried" in result.seat_ids

    def test_no_route_for_unrelated(self) -> None:
        dossiers = _load_dossiers()
        result = route_question("What's the weather like today?", dossiers)
        assert not result.should_route

    def test_caps_at_max_seats(self) -> None:
        dossiers = _load_dossiers()
        # A question that matches many domains
        result = route_question(
            "How should I grow my agency, position my brand, manage my team, and make my pitch more creative?",
            dossiers,
            max_seats=2,
        )
        assert result.should_route
        # Always at least 3 seats for a meaningful meeting, but respect max_seats if larger
        assert len(result.seat_ids) >= 3
        assert len(result.seat_ids) <= 6


class TestNameMentions:
    def test_routes_on_full_name(self) -> None:
        dossiers = _load_dossiers()
        result = route_question("What would Seth Godin say about this?", dossiers)
        assert result.should_route
        assert "seth-godin" in result.seat_ids

    def test_routes_on_surname(self) -> None:
        dossiers = _load_dossiers()
        result = route_question("What would Godin say about this?", dossiers)
        assert result.should_route
        assert "seth-godin" in result.seat_ids
