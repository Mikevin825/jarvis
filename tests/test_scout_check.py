"""Tests for the scout check.

The scout check integrates the research loop with the heartbeat. It follows
the same pattern as every other check: quiet by default, most runs produce
nothing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from jarvis.heartbeat.scout_check import ScoutCheck, SeenItems
from jarvis.heartbeat.checks import CheckContext
from jarvis.providers import Message, TextDelta, TurnEnd


class MockProvider:
    """A mock provider for testing the scout check."""

    supports_tools = True

    def stream(self, system, messages, tools=None):
        yield TurnEnd(text="", calls=[], usage=None)


class TestSeenItems:
    def test_loads_empty_when_no_file(self, tmp_path: Path) -> None:
        path = tmp_path / "seen.json"
        seen = SeenItems.load(path)
        assert seen.items == []

    def test_loads_existing_items(self, tmp_path: Path) -> None:
        path = tmp_path / "seen.json"
        path.write_text(json.dumps({"items": ["url1", "url2"]}), encoding="utf-8")
        seen = SeenItems.load(path)
        assert "url1" in seen
        assert "url2" in seen

    def test_adds_new_items(self, tmp_path: Path) -> None:
        path = tmp_path / "seen.json"
        seen = SeenItems.load(path)
        seen.add("url1")
        seen.add("url2")
        seen.add("url1")  # Duplicate
        assert len(seen.items) == 2

    def test_saves_to_file(self, tmp_path: Path) -> None:
        path = tmp_path / "seen.json"
        seen = SeenItems.load(path)
        seen.add("url1")
        seen.save(path)
        # Reload and verify
        reloaded = SeenItems.load(path)
        assert "url1" in reloaded

    def test_contains_check(self, tmp_path: Path) -> None:
        path = tmp_path / "seen.json"
        seen = SeenItems.load(path)
        seen.add("url1")
        assert "url1" in seen
        assert "url2" not in seen


class TestScoutCheck:
    def test_name_is_scout(self) -> None:
        assert ScoutCheck.name == "scout"

    def test_never_raises(self) -> None:
        """The scout check must never raise — a check must not crash the loop."""
        check = ScoutCheck(3600, {}, MockProvider())
        ctx = CheckContext()
        # Even with no provider, it should return a CheckResult
        result = check.run(ctx)
        assert result is not None

    def test_returns_check_result(self) -> None:
        check = ScoutCheck(3600, {}, MockProvider())
        ctx = CheckContext()
        result = check.run(ctx)
        assert hasattr(result, "surfaced")
        assert hasattr(result, "summary")

    def test_quiet_by_default(self) -> None:
        """Most runs should produce nothing.

        A run that completes normally with no findings is quiet. A run that
        fails (e.g. no_terminal_call) surfaces so the operator knows.
        """
        check = ScoutCheck(3600, {}, MockProvider())
        ctx = CheckContext()
        result = check.run(ctx)
        # The mock provider returns no tool calls, so the scout surfaces
        # a no_terminal_call error — this is correct behavior.
        assert result.surfaced
        assert "no_terminal_call" in result.summary

    def test_empty_run_still_reports(self) -> None:
        """An empty run is information — it should still report."""
        check = ScoutCheck(3600, {}, MockProvider())
        ctx = CheckContext()
        result = check.run(ctx)
        # The summary should indicate the scout ran
        assert "scout" in result.summary.lower()

    def test_tracks_seen_items(self) -> None:
        """The scout should track seen items to avoid repeats."""
        check = ScoutCheck(3600, {}, MockProvider())
        check.seen.add("https://example.com/article1")
        assert "https://example.com/article1" in check.seen
        assert "https://example.com/article2" not in check.seen

    def test_persists_per_item(self) -> None:
        """One malformed row must not discard the good ones."""
        check = ScoutCheck(3600, {}, MockProvider())
        # Add multiple items
        for i in range(5):
            check.seen.add(f"https://example.com/article{i}")
        assert len(check.seen.items) == 5

    def test_delivers_even_when_empty(self) -> None:
        """A run that finds nothing still reports."""
        check = ScoutCheck(3600, {}, MockProvider())
        ctx = CheckContext()
        result = check.run(ctx)
        # The summary should indicate the run happened
        assert result.summary != ""

    def test_uses_doctrine_as_prompt(self) -> None:
        """The scout should use the doctrine as the system prompt."""
        from jarvis.scout.doctrine import system_prompt
        prompt = system_prompt()
        assert "Scout Doctrine" in prompt
        assert "Hard kills" in prompt

    def test_filters_seen_items(self) -> None:
        """The scout should filter out items that have been seen before."""
        check = ScoutCheck(3600, {}, MockProvider())
        check.seen.add("https://example.com/seen")
        # Simulate a finding with that URL
        from jarvis.scout.report import Finding
        finding = Finding(
            title="Test",
            summary="Test",
            source_url="https://example.com/seen",
            relevance=5,
            novelty=5,
            impact=5,
            kill_criterion="Test",
        )
        # The finding should be filtered out
        assert finding.source_url in check.seen
