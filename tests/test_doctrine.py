"""Tests for the doctrine loader.

The doctrine is the scout's instruction set. It is data, not code. The loader
caches on mtime so that a hand edit to the file is picked up on the next run
without restarting the process.
"""

from __future__ import annotations

from pathlib import Path

from jarvis.scout.doctrine import (
    DOCTRINE_PATH,
    invalidate_cache,
    load_document,
    system_prompt,
)


class TestLoadDocument:
    def test_loads_real_doctrine(self) -> None:
        content = load_document()
        assert "Scout Doctrine" in content
        assert "Hard kills" in content
        assert "Rubric" in content

    def test_caches_on_mtime(self, tmp_path: Path) -> None:
        doc = tmp_path / "DOCTRINE.md"
        doc.write_text("First version", encoding="utf-8")

        first = load_document(doc)
        assert first == "First version"

        # Second call should return cached content (same mtime).
        second = load_document(doc)
        assert second == "First version"

    def test_reloads_when_mtime_changes(self, tmp_path: Path) -> None:
        doc = tmp_path / "DOCTRINE.md"
        doc.write_text("First version", encoding="utf-8")

        first = load_document(doc)
        assert first == "First version"

        # Simulate an edit by writing new content and bumping mtime.
        doc.write_text("Second version", encoding="utf-8")
        # Ensure mtime changes (some filesystems have coarse granularity).
        import os
        import time
        os.utime(doc, (time.time() + 1, time.time() + 1))

        second = load_document(doc)
        assert second == "Second version"

    def test_fallback_when_file_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.md"
        content = load_document(missing)
        assert "research scout" in content
        assert "recommend" in content

    def test_fallback_when_file_unreadable(self, tmp_path: Path) -> None:
        doc = tmp_path / "DOCTRINE.md"
        doc.write_text("Secret", encoding="utf-8")
        doc.chmod(0o000)

        try:
            content = load_document(doc)
            assert "research scout" in content
        finally:
            doc.chmod(0o644)

    def test_invalidate_cache_forces_reload(self, tmp_path: Path) -> None:
        doc = tmp_path / "DOCTRINE.md"
        doc.write_text("First version", encoding="utf-8")

        first = load_document(doc)
        assert first == "First version"

        # Invalidate and write new content with same mtime.
        invalidate_cache()
        doc.write_text("Second version", encoding="utf-8")

        second = load_document(doc)
        assert second == "Second version"


class TestSystemPrompt:
    def test_returns_doctrine_content(self) -> None:
        prompt = system_prompt()
        assert "Scout Doctrine" in prompt
        assert "Hard kills" in prompt
        assert "Rubric" in prompt
        assert "You recommend, the human decides" in prompt

    def test_contains_hard_kills(self) -> None:
        prompt = system_prompt()
        assert "Never act on a find" in prompt
        assert "Never propose anything confidential" in prompt
        assert "Never use paid sources" in prompt
        assert "Never repeat a finding" in prompt
        assert "Never surface a finding below the threshold" in prompt

    def test_contains_rubric(self) -> None:
        prompt = system_prompt()
        assert "Relevance" in prompt
        assert "Novelty" in prompt
        assert "Impact" in prompt
        assert "3.0" in prompt

    def test_contains_tool_authority(self) -> None:
        prompt = system_prompt()
        assert "web_search" in prompt
        assert "fetch_rss" in prompt
        assert "fetch_url" in prompt

    def test_contains_discipline(self) -> None:
        prompt = system_prompt()
        assert "evidence is thin" in prompt
        assert "sources conflict" in prompt
        assert "nothing is found" in prompt
        assert "model is uncertain" in prompt
