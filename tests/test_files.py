"""Tests for the file listing tool.

A read-only tool that lists files in a directory. Useful for finding
files, checking what's in a folder, or locating specific file types.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.tools.base import ToolError
from jarvis.tools.files import list_files


class TestListFiles:
    def test_lists_files_in_directory(self, tmp_path: Path) -> None:
        (tmp_path / "file1.txt").write_text("hello")
        (tmp_path / "file2.txt").write_text("world")

        result = list_files(str(tmp_path))
        assert "file1.txt" in result
        assert "file2.txt" in result

    def test_filters_by_pattern(self, tmp_path: Path) -> None:
        (tmp_path / "song.mp3").write_text("audio")
        (tmp_path / "notes.txt").write_text("text")

        result = list_files(str(tmp_path), pattern="*.mp3")
        assert "song.mp3" in result
        assert "notes.txt" not in result

    def test_returns_message_when_no_files(self, tmp_path: Path) -> None:
        result = list_files(str(tmp_path))
        assert "No files found" in result

    def test_raises_for_nonexistent_path(self) -> None:
        with pytest.raises(ToolError, match="does not exist"):
            list_files("/nonexistent/path/12345")

    def test_raises_for_file_not_directory(self, tmp_path: Path) -> None:
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")

        with pytest.raises(ToolError, match="not a directory"):
            list_files(str(file_path))

    def test_resolves_home_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "test.txt").write_text("content")

        result = list_files("~")
        assert "test.txt" in result

    def test_shows_file_sizes(self, tmp_path: Path) -> None:
        (tmp_path / "small.txt").write_text("hi")
        (tmp_path / "large.txt").write_text("x" * 2048)

        result = list_files(str(tmp_path))
        assert "small.txt" in result
        assert "large.txt" in result

    def test_respects_max_results(self, tmp_path: Path) -> None:
        for i in range(10):
            (tmp_path / f"file{i}.txt").write_text("content")

        result = list_files(str(tmp_path), max_results=3)
        # The count is the real total, not the number shown — telling the model
        # "3 file(s)" when ten exist would hide that seven were cut off.
        assert "10 file(s)" in result
        assert "and 7 more" in result
        assert "file2.txt" in result
        assert "file3.txt" not in result, "the 4th file should have been cut off"
