"""Tests for the adversarial fact-check.

Stage two of the research process. A separate pass, without access to the
researcher's reasoning, instructed to try to refute each entry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.board.dossier import DoctrineEntry, parse_dossier
from jarvis.board.factcheck import FactCheckReport, fact_check_dossier


class TestFactCheckDossier:
    def test_marks_all_as_user_without_provider(self, tmp_path: Path) -> None:
        """Without a provider, all entries are marked as user (conservative default)."""
        content = """---
id: test
name: Test Person
seat_title: Test
domains: marketing
---

# Test

## Doctrine

### D1
Some doctrine.
Source: Some source
"""
        path = tmp_path / "test.md"
        path.write_text(content, encoding="utf-8")
        dossier = parse_dossier(path)
        assert dossier is not None

        report = fact_check_dossier(dossier, provider=None)
        assert len(report.results) == 1
        assert report.results[0].status == "user"
        assert report.results[0].entry_id == "D1"
        assert report.confirmed == 0
        assert report.rejected == 0
        assert report.user_entries == 1

    def test_report_summary(self, tmp_path: Path) -> None:
        content = """---
id: test
name: Test Person
seat_title: Test
domains: marketing
---

# Test

## Doctrine

### D1
Some doctrine.
Source: Some source

### D2
More doctrine.
Source: Another source
"""
        path = tmp_path / "test.md"
        path.write_text(content, encoding="utf-8")
        dossier = parse_dossier(path)
        assert dossier is not None

        report = fact_check_dossier(dossier, provider=None)
        assert "Test Person" in report.summary()
        assert "0 confirmed" in report.summary()
        assert "2 user entries" in report.summary()

    def test_fact_check_result_fields(self) -> None:
        from jarvis.board.factcheck import FactCheckResult

        result = FactCheckResult(
            entry_id="D1",
            title="Test title",
            source="Test source",
            status="sourced",
            notes="Verified",
        )
        assert result.entry_id == "D1"
        assert result.status == "sourced"
        assert result.notes == "Verified"

    def test_fact_check_report_fields(self) -> None:
        from jarvis.board.factcheck import FactCheckResult

        report = FactCheckReport(seat_id="test", seat_name="Test")
        report.results.append(
            FactCheckResult(
                entry_id="D1",
                title="Test",
                source="Source",
                status="sourced",
            )
        )
        report.results.append(
            FactCheckResult(
                entry_id="D2",
                title="Test 2",
                source="Source 2",
                status="rejected",
            )
        )
        assert report.confirmed == 1
        assert report.rejected == 1
        assert report.user_entries == 0


class TestDossierParsing:
    def test_all_four_dossiers_parse(self) -> None:
        """All four dossiers in the dossiers directory should parse."""
        dossiers_dir = Path(__file__).resolve().parent.parent / "jarvis" / "board" / "dossiers"
        if not dossiers_dir.exists():
            pytest.skip("Dossiers directory not found")

        dossiers = list(dossiers_dir.glob("*.md"))
        assert len(dossiers) >= 4, f"Expected at least 4 dossiers, found {len(dossiers)}"

        for path in dossiers:
            dossier = parse_dossier(path)
            assert dossier is not None, f"Failed to parse {path.name}"
            assert len(dossier.doctrine) > 0, f"No doctrine in {path.name}"
            assert len(dossier.domains) > 0, f"No domains in {path.name}"

    def test_godin_dossier_has_expected_entries(self) -> None:
        dossiers_dir = Path(__file__).resolve().parent.parent / "jarvis" / "board" / "dossiers"
        path = dossiers_dir / "seth-godin.md"
        if not path.exists():
            pytest.skip("seth-godin.md not found")

        dossier = parse_dossier(path)
        assert dossier is not None
        assert dossier.name == "Seth Godin"
        assert "marketing" in dossier.domains
        assert len(dossier.doctrine) >= 6
        assert dossier.doctrine_ids == {"D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"}

    def test_arden_dossier_has_expected_entries(self) -> None:
        dossiers_dir = Path(__file__).resolve().parent.parent / "jarvis" / "board" / "dossiers"
        path = dossiers_dir / "paul-arden.md"
        if not path.exists():
            pytest.skip("paul-arden.md not found")

        dossier = parse_dossier(path)
        assert dossier is not None
        assert dossier.name == "Paul Arden"
        assert "creativity" in dossier.domains
        assert len(dossier.doctrine) >= 6

    def test_neumeier_dossier_has_expected_entries(self) -> None:
        dossiers_dir = Path(__file__).resolve().parent.parent / "jarvis" / "board" / "dossiers"
        path = dossiers_dir / "marty-neumeier.md"
        if not path.exists():
            pytest.skip("marty-neumeier.md not found")

        dossier = parse_dossier(path)
        assert dossier is not None
        assert dossier.name == "Marty Neumeier"
        assert "branding" in dossier.domains
        assert len(dossier.doctrine) >= 6

    def test_fried_dossier_has_expected_entries(self) -> None:
        dossiers_dir = Path(__file__).resolve().parent.parent / "jarvis" / "board" / "dossiers"
        path = dossiers_dir / "jason-fried.md"
        if not path.exists():
            pytest.skip("jason-fried.md not found")

        dossier = parse_dossier(path)
        assert dossier is not None
        assert dossier.name == "Jason Fried"
        assert "operations" in dossier.domains
        assert len(dossier.doctrine) >= 6
