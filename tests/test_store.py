"""Tests for the meeting store and editor.

Store every meeting with citation snapshots. Make seats editable with two
rules: retire never delete, and never let the user edit verification state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.board.dossier import parse_dossier
from jarvis.board.editor import (
    add_entry,
    edit_entry_source,
    edit_entry_text,
    retire_entry,
    save_dossier,
)
from jarvis.board.store import MeetingStore, StoredCitation, StoredMeeting, StoredOpinion


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


class TestMeetingStore:
    def test_stores_and_retrieves_meetings(self, tmp_path: Path) -> None:
        store = MeetingStore(tmp_path / "meetings.json")
        meeting = StoredMeeting(
            id="m1",
            question="Should I raise prices?",
            opinions=[
                StoredOpinion(
                    seat_id="seth-godin",
                    seat_name="Seth Godin",
                    position="Yes",
                    reasoning="Because",
                    citations=[StoredCitation(entry_id="D1", title="Test", source="Source", verification="sourced")],
                    confidence=4,
                ),
            ],
            synthesis="The board split.",
            total_cost_usd=0.05,
        )
        store.store(meeting)

        assert store.count() == 1
        retrieved = store.get("m1")
        assert retrieved is not None
        assert retrieved.question == "Should I raise prices?"
        assert len(retrieved.opinions) == 1
        assert retrieved.opinions[0].citations[0].entry_id == "D1"

    def test_persists_to_disk(self, tmp_path: Path) -> None:
        store = MeetingStore(tmp_path / "meetings.json")
        store.store(StoredMeeting(id="m1", question="Test"))

        store2 = MeetingStore(tmp_path / "meetings.json")
        store2.load()
        assert store2.count() == 1

    def test_all_returns_newest_first(self, tmp_path: Path) -> None:
        store = MeetingStore(tmp_path / "meetings.json")
        store.store(StoredMeeting(id="m1", question="First"))
        store.store(StoredMeeting(id="m2", question="Second"))

        all_meetings = store.all()
        assert len(all_meetings) == 2
        assert all_meetings[0].id == "m2"
        assert all_meetings[1].id == "m1"

    def test_get_returns_none_for_unknown_id(self, tmp_path: Path) -> None:
        store = MeetingStore(tmp_path / "meetings.json")
        assert store.get("nonexistent") is None


class TestRetireEntry:
    def test_retires_without_deleting(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier = dossiers[0]
        original_count = len(dossier.doctrine)
        result = retire_entry(dossier, "D1")

        assert result.ok
        # Count should be the same — no deletion
        assert len(dossier.doctrine) == original_count
        # Entry should be marked as retired
        assert "[RETIRED]" in dossier.doctrine[0].text

    def test_retire_returns_false_for_unknown_id(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        result = retire_entry(dossiers[0], "D999")
        assert not result.ok


class TestEditEntryText:
    def test_drops_verification_to_user(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier = dossiers[0]
        original_text = dossier.doctrine[0].text
        result = edit_entry_text(dossier, "D1", "New text that is different")

        assert result.ok
        assert dossier.doctrine[0].text == "New text that is different"
        assert dossier.doctrine[0].verification == "user"

    def test_returns_false_for_unchanged_text(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier = dossiers[0]
        original_text = dossier.doctrine[0].text
        result = edit_entry_text(dossier, "D1", original_text)

        assert not result.ok


class TestEditEntrySource:
    def test_drops_verification_to_user(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier = dossiers[0]
        result = edit_entry_source(dossier, "D1", "New source (2024)")

        assert result.ok
        assert dossier.doctrine[0].source == "New source (2024)"
        assert dossier.doctrine[0].verification == "user"


class TestAddEntry:
    def test_adds_with_user_verification(self) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier = dossiers[0]
        original_count = len(dossier.doctrine)
        result = add_entry(dossier, "New doctrine entry", "New source")

        assert result.ok
        assert len(dossier.doctrine) == original_count + 1
        new_entry = dossier.doctrine[-1]
        assert new_entry.verification == "user"
        assert new_entry.text == "New doctrine entry"


class TestSaveDossier:
    def test_saves_and_reparses(self, tmp_path: Path) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier = dossiers[0]
        path = tmp_path / "test-dossier.md"
        result = save_dossier(dossier, path)

        assert result.ok
        assert path.exists()

        # Re-parse and verify
        reparsed = parse_dossier(path)
        assert reparsed is not None
        assert reparsed.name == dossier.name
        assert len(reparsed.doctrine) == len(dossier.doctrine)
