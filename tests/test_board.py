"""Tests for the board of advisors — Tier 1: dossier format and citation gate.

The parser reads one markdown file and returns a structured seat, or nothing.
The citation gate is a pure function that filters citations to only those
that exist in the seat's dossier.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.board.dossier import DossierError, parse_dossier
from jarvis.board.gate import CitationGate, filter_citations


def _write_dossier(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _valid_dossier_content() -> str:
    return """---
id: seth-godin
name: Seth Godin
seat_title: Growth & Marketing
domains: marketing, agency-growth, positioning
status: active
---

# Seth Godin — Growth & Marketing

## Doctrine

### D1
People like us do things. The most powerful marketing is not about reaching
everyone, it's about reaching the people who care.
Source: "This is Marketing" (2018), Chapter 3

### D2
Permission marketing is the privilege of delivering anticipated, personal,
relevant messages to people who actually want to get them.
Source: "Permission Marketing" (1999), Chapter 1

### D3
The only way to grow is to do work that matters to the people you serve.
Source: "Linchpin" (2010), Chapter 5

## Characteristic objection

Are you trying to reach everyone? Because that means you're trying to reach
no one. Who is this actually for?

## Blind spots

- His framework assumes you have something worth saying. He has little to
  say about what to do when you don't.
- The "people like us" framing can become an echo chamber if you're not
  careful about who you let in.

## Voice

Direct, short sentences. No jargon. He writes like he talks — plain,
conversational, and always in service of the idea.
"""


class TestParseDossier:
    def test_parses_valid_dossier(self, tmp_path: Path) -> None:
        path = tmp_path / "seth-godin.md"
        _write_dossier(path, _valid_dossier_content())
        dossier = parse_dossier(path)
        assert dossier is not None
        assert dossier.id == "seth-godin"
        assert dossier.name == "Seth Godin"
        assert dossier.seat_title == "Growth & Marketing"
        assert "marketing" in dossier.domains
        assert len(dossier.doctrine) == 3
        assert dossier.doctrine[0].id == "D1"
        assert "People like us" in dossier.doctrine[0].text
        assert dossier.doctrine[0].source == '"This is Marketing" (2018), Chapter 3'

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        assert parse_dossier(tmp_path / "nonexistent.md") is None

    def test_rejects_no_domains(self, tmp_path: Path) -> None:
        content = """---
id: test
name: Test Person
seat_title: Test
domains:
---

# Test

## Doctrine

### D1
Some doctrine.
Source: Some source
"""
        path = tmp_path / "test.md"
        _write_dossier(path, content)
        with pytest.raises(DossierError, match="no domains"):
            parse_dossier(path)

    def test_rejects_no_doctrine(self, tmp_path: Path) -> None:
        content = """---
id: test
name: Test Person
seat_title: Test
domains: marketing
---

# Test

## Doctrine

(no entries)
"""
        path = tmp_path / "test.md"
        _write_dossier(path, content)
        with pytest.raises(DossierError, match="no doctrine"):
            parse_dossier(path)

    def test_rejects_duplicate_ids(self, tmp_path: Path) -> None:
        content = """---
id: test
name: Test Person
seat_title: Test
domains: marketing
---

# Test

## Doctrine

### D1
First entry.
Source: Source 1

### D1
Second entry with same id.
Source: Source 2
"""
        path = tmp_path / "test.md"
        _write_dossier(path, content)
        with pytest.raises(DossierError, match="duplicate doctrine ids"):
            parse_dossier(path)

    def test_parses_objection_and_blind_spots(self, tmp_path: Path) -> None:
        path = tmp_path / "test.md"
        _write_dossier(path, _valid_dossier_content())
        dossier = parse_dossier(path)
        assert dossier is not None
        assert "everyone" in dossier.objection
        assert len(dossier.blind_spots) == 2
        assert "echo chamber" in dossier.blind_spots[1]

    def test_parses_voice(self, tmp_path: Path) -> None:
        path = tmp_path / "test.md"
        _write_dossier(path, _valid_dossier_content())
        dossier = parse_dossier(path)
        assert dossier is not None
        assert "Direct" in dossier.voice

    def test_doctrine_ids_property(self, tmp_path: Path) -> None:
        path = tmp_path / "test.md"
        _write_dossier(path, _valid_dossier_content())
        dossier = parse_dossier(path)
        assert dossier is not None
        assert dossier.doctrine_ids == {"D1", "D2", "D3"}

    def test_to_prompt_contains_dossier(self, tmp_path: Path) -> None:
        path = tmp_path / "test.md"
        _write_dossier(path, _valid_dossier_content())
        dossier = parse_dossier(path)
        assert dossier is not None
        prompt = dossier.to_prompt()
        assert "Seth Godin" in prompt
        assert "D1" in prompt
        assert "D2" in prompt
        assert "D3" in prompt
        assert "People like us" in prompt


class TestFilterCitations:
    def test_filters_valid_citations(self) -> None:
        result = filter_citations(["D1", "D2", "D3"], {"D1", "D2", "D3"})
        assert result == ["D1", "D2", "D3"]

    def test_strips_invalid_citations(self) -> None:
        result = filter_citations(["D1", "D99", "D2"], {"D1", "D2", "D3"})
        assert result == ["D1", "D2"]

    def test_uppercase_normalizes(self) -> None:
        result = filter_citations(["d1", "D2"], {"D1", "D2", "D3"})
        assert result == ["D1", "D2"]

    def test_deduplicates(self) -> None:
        result = filter_citations(["D1", "D1", "D2"], {"D1", "D2", "D3"})
        assert result == ["D1", "D2"]

    def test_preserves_order(self) -> None:
        result = filter_citations(["D3", "D1", "D2"], {"D1", "D2", "D3"})
        assert result == ["D3", "D1", "D2"]

    def test_handles_none(self) -> None:
        assert filter_citations(None, {"D1", "D2"}) == []

    def test_handles_empty_list(self) -> None:
        assert filter_citations([], {"D1", "D2"}) == []

    def test_extracts_citations_from_text(self) -> None:
        result = filter_citations(
            ["As I said in D3, this is important. Also see D1."],
            {"D1", "D2", "D3"},
        )
        assert result == ["D3", "D1"]

    def test_handles_non_string_items(self) -> None:
        result = filter_citations([None, 123, "D1"], {"D1", "D2"})
        assert result == ["D1"]


class TestCitationGate:
    def test_valid_citations(self) -> None:
        gate = CitationGate({"D1", "D2", "D3"})
        result = gate.check(["D1", "D2"], abstained=False)
        assert result == ["D1", "D2"]
        assert not gate.unsourced

    def test_fabricated_citations_stripped(self) -> None:
        gate = CitationGate({"D1", "D2", "D3"})
        result = gate.check(["D1", "D99", "D2"], abstained=False)
        assert result == ["D1", "D2"]
        assert gate.fabricated == ["D99"]

    def test_unsourced_when_no_citations_and_not_abstained(self) -> None:
        gate = CitationGate({"D1", "D2", "D3"})
        gate.check([], abstained=False)
        assert gate.unsourced

    def test_not_unsourced_when_abstained(self) -> None:
        gate = CitationGate({"D1", "D2", "D3"})
        gate.check([], abstained=True)
        assert not gate.unsourced

    def test_not_unsourced_when_citations_valid(self) -> None:
        gate = CitationGate({"D1", "D2", "D3"})
        gate.check(["D1"], abstained=False)
        assert not gate.unsourced
