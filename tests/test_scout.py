"""Tests for the scout's pure logic.

The research loop itself requires a provider (not available in tests), but
the coercion, salvage, and schema validation are pure functions that can be
tested without a GPU or a model.
"""

from __future__ import annotations

from jarvis.scout.loop import (
    _EMIT_REPORT_SCHEMA,
    _coerce_finding,
    _salvage_report,
)
from jarvis.scout.report import Finding, ScoutReport


class TestCoerceFinding:
    def test_valid_finding(self) -> None:
        raw = {
            "title": "OpenAI launches new model",
            "summary": "GPT-5 released with improved reasoning",
            "source_url": "https://openai.com/blog/gpt5",
            "relevance": 5,
            "novelty": 4,
            "impact": 5,
            "kill_criterion": "Abandon if no follow-up in 7 days",
            "seen_before": False,
        }
        finding = _coerce_finding(raw)
        assert finding is not None
        assert finding.title == "OpenAI launches new model"
        assert finding.relevance == 5
        assert finding.novelty == 4
        assert finding.impact == 5

    def test_clamps_scores_to_range(self) -> None:
        raw = {
            "title": "Test",
            "summary": "Test",
            "source_url": "https://example.com",
            "relevance": 10,
            "novelty": 0,
            "impact": -1,
            "kill_criterion": "Test",
        }
        finding = _coerce_finding(raw)
        assert finding is not None
        assert finding.relevance == 5
        assert finding.novelty == 1
        assert finding.impact == 1

    def test_returns_none_for_invalid(self) -> None:
        assert _coerce_finding({"title": 123}) is None
        assert _coerce_finding({"title": None}) is None
        assert _coerce_finding("not a dict") is None
        assert _coerce_finding(None) is None

    def test_handles_missing_optional_fields(self) -> None:
        raw = {
            "title": "Test",
            "summary": "Test",
            "source_url": "https://example.com",
            "relevance": 3,
            "novelty": 3,
            "impact": 3,
            "kill_criterion": "Test",
        }
        finding = _coerce_finding(raw)
        assert finding is not None
        assert finding.seen_before is False


class TestSalvageReport:
    def test_valid_report(self) -> None:
        raw = {
            "findings": [
                {
                    "title": "A",
                    "summary": "A",
                    "source_url": "https://a.com",
                    "relevance": 5,
                    "novelty": 4,
                    "impact": 5,
                    "kill_criterion": "A",
                },
                {
                    "title": "B",
                    "summary": "B",
                    "source_url": "https://b.com",
                    "relevance": 3,
                    "novelty": 3,
                    "impact": 3,
                    "kill_criterion": "B",
                },
            ]
        }
        findings, note = _salvage_report(raw)
        assert len(findings) == 2
        assert note == ""

    def test_drops_invalid_findings(self) -> None:
        raw = {
            "findings": [
                {
                    "title": "Valid",
                    "summary": "Valid",
                    "source_url": "https://valid.com",
                    "relevance": 5,
                    "novelty": 4,
                    "impact": 5,
                    "kill_criterion": "Valid",
                },
                {"title": 123},  # invalid
                "not a dict",  # invalid
            ]
        }
        findings, note = _salvage_report(raw)
        assert len(findings) == 1
        assert "2 finding(s) dropped" in note

    def test_empty_findings(self) -> None:
        findings, note = _salvage_report({"findings": []})
        assert findings == []
        assert note == ""

    def test_no_findings_key(self) -> None:
        findings, note = _salvage_report({})
        assert findings == []
        assert "no findings array" in note

    def test_none_input(self) -> None:
        findings, note = _salvage_report(None)
        assert findings == []
        assert "no report was emitted" in note


class TestEmitReportSchema:
    def test_schema_has_required_fields(self) -> None:
        props = _EMIT_REPORT_SCHEMA["properties"]["findings"]["items"]["properties"]
        assert "title" in props
        assert "summary" in props
        assert "source_url" in props
        assert "relevance" in props
        assert "novelty" in props
        assert "impact" in props
        assert "kill_criterion" in props

    def test_schema_requires_fields(self) -> None:
        required = _EMIT_REPORT_SCHEMA["properties"]["findings"]["items"]["required"]
        assert "title" in required
        assert "summary" in required
        assert "source_url" in required
        assert "relevance" in required
        assert "novelty" in required
        assert "impact" in required
        assert "kill_criterion" in required

    def test_schema_constrains_scores(self) -> None:
        props = _EMIT_REPORT_SCHEMA["properties"]["findings"]["items"]["properties"]
        assert props["relevance"]["minimum"] == 1
        assert props["relevance"]["maximum"] == 5
        assert props["novelty"]["minimum"] == 1
        assert props["novelty"]["maximum"] == 5
        assert props["impact"]["minimum"] == 1
        assert props["impact"]["maximum"] == 5


class TestScoutReport:
    def test_report_has_stop_reason(self) -> None:
        report = ScoutReport(
            findings=[],
            searched=[],
            cost_usd=0.0,
            iterations=0,
            wall_clock_s=0.0,
            stop_reason="completed",
        )
        assert report.stop_reason == "completed"
        assert report.error is None

    def test_report_with_error(self) -> None:
        report = ScoutReport(
            findings=[],
            searched=[],
            cost_usd=0.0,
            iterations=0,
            wall_clock_s=0.0,
            stop_reason="error",
            error="test error",
        )
        assert report.stop_reason == "error"
        assert report.error == "test error"
