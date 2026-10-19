"""Tests for the meeting store and editor.

Store every meeting — question, seats, opinions, synthesis, cost, with
citation snapshots. Make the seats editable — retire never delete, never
let the user edit verification state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.board.chair import ChairSynthesis
from jarvis.board.dossier import parse_dossier
from jarvis.board.editor import (
    add_entry,
    edit_entry_source,
    edit_entry_text,
    retire_entry,
    save_dossier,
)
from jarvis.board.meeting import SeatOpinion
from jarvis.board.storage import MeetingStore, StoredCitation, StoredMeeting, StoredOpinion


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
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier_map = {d.id: d for d in dossiers}
        opinion = SeatOpinion(
            seat_id=dossiers[0].id,
            seat_name=dossiers[0].name,
            position="Yes",
            reasoning="Because",
            citations=["D1"],
            confidence=4,
            would_change_mind="No",
            abstains=False,
        )
        synthesis = ChairSynthesis(
            summary="The board split on pricing.",
            split="Godin said yes, Fried said no.",
            agreement="They agreed on timing.",
            unanimous=False,
        )

        meeting = store.store(
            question="Should I raise prices?",
            opinions=[opinion],
            synthesis=synthesis,
            dossiers=dossier_map,
            total_cost_usd=0.05,
            total_wall_clock_s=10.0,
        )

        assert meeting.id
        assert meeting.question == "Should I raise prices?"
        assert len(meeting.opinions) == 1
        assert meeting.opinions[0].citations[0].entry_id == "D1"

    def test_recent_returns_newest_first(self, tmp_path: Path) -> None:
        store = MeetingStore(tmp_path / "meetings.json")
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier_map = {d.id: d for d in dossiers}
        synthesis = ChairSynthesis(summary="Test", split="", agreement="")

        store.store("Question 1", [], synthesis, dossier_map)
        store.store("Question 2", [], synthesis, dossier_map)
        store.store("Question 3", [], synthesis, dossier_map)

        recent = store.recent(count=2)
        assert len(recent) == 2
        assert recent[0].question == "Question 3"
        assert recent[1].question == "Question 2"

    def test_persists_to_disk(self, tmp_path: Path) -> None:
        store = MeetingStore(tmp_path / "meetings.json")
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier_map = {d.id: d for d in dossiers}
        synthesis = ChairSynthesis(summary="Test", split="", agreement="")

        store.store("Test question", [], synthesis, dossier_map)

        # Create a new store instance and load
        store2 = MeetingStore(tmp_path / "meetings.json")
        meetings = store2.all()
        assert len(meetings) == 1
        assert meetings[0].question == "Test question"

    def test_citation_snapshots_stored(self, tmp_path: Path) -> None:
        store = MeetingStore(tmp_path / "meetings.json")
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier_map = {d.id: d for d in dossiers}
        opinion = SeatOpinion(
            seat_id=dossiers[0].id,
            seat_name=dossiers[0].name,
            position="Yes",
            reasoning="Because",
            citations=["D1", "D2"],
            confidence=4,
            would_change_mind="No",
            abstains=False,
        )
        synthesis = ChairSynthesis(summary="Test", split="", agreement="")

        meeting = store.store("Test", [opinion], synthesis, dossier_map)

        assert len(meeting.opinions[0].citations) == 2
        assert meeting.opinions[0].citations[0].entry_id == "D1"
        assert meeting.opinions[0].citations[0].title != ""
        assert meeting.opinions[0].citations[0].source != ""


class TestEditor:
    def test_retire_entry_marks_retired(self, tmp_path: Path) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier = dossiers[0]
        result = retire_entry(dossier, "D1")
        assert result.ok
        assert "retired" in result.message.lower()

        # The entry should still exist but be marked as retired
        entry = next(e for e in dossier.doctrine if e.id == "D1")
        assert entry.text.startswith("[RETIRED]")

    def test_retire_nonexistent_entry(self, tmp_path: Path) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier = dossiers[0]
        result = retire_entry(dossier, "D999")
        assert not result.ok

    def test_edit_text_drops_verification(self, tmp_path: Path) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier = dossiers[0]
        original_text = dossier.doctrine[0].text
        result = edit_entry_text(dossier, "D1", "New text that is different")
        assert result.ok
        assert "user" in result.message.lower()

        entry = next(e for e in dossier.doctrine if e.id == "D1")
        assert entry.text == "New text that is different"
        assert entry.verification == "user"

    def test_edit_text_no_change(self, tmp_path: Path) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier = dossiers[0]
        original_text = dossier.doctrine[0].text
        result = edit_entry_text(dossier, "D1", original_text)
        assert not result.ok

    def test_edit_source_drops_verification(self, tmp_path: Path) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier = dossiers[0]
        result = edit_entry_source(dossier, "D1", "New source (2024)")
        assert result.ok
        assert "user" in result.message.lower()

        entry = next(e for e in dossier.doctrine if e.id == "D1")
        assert entry.source == "New source (2024)"
        assert entry.verification == "user"

    def test_add_entry_assigns_next_id(self, tmp_path: Path) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier = dossiers[0]
        existing_ids = {e.id for e in dossier.doctrine}
        next_num = 1
        while f"D{next_num}" in existing_ids:
            next_num += 1

        result = add_entry(dossier, "New doctrine entry", "New source")
        assert result.ok
        assert f"D{next_num}" in result.message

        new_entry = next(e for e in dossier.doctrine if e.id == f"D{next_num}")
        assert new_entry.verification == "user"

    def test_save_dossier_writes_file(self, tmp_path: Path) -> None:
        dossiers = _load_dossiers()
        if not dossiers:
            pytest.skip("No dossiers found")

        dossier = dossiers[0]
        path = tmp_path / "test-dossier.md"
        path.write_text("# Test", encoding="utf-8")

        result = save_dossier(dossier, path)
        assert result.ok

        # Reload and verify
        reloaded = parse_dossier(path)
        assert reloaded is not None
        assert reloaded.name == dossier.name
        assert len(reloaded.doctrine) == len(dossier.doctrine)
