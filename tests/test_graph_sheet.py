"""Tests for the graph sheet and the website metrics behind it.

The chart engine is tested on its output shape (valid SVG, gaps drawn as gaps,
no external references) and the sheet on its structure. The data layer is
tested by recording synthetic history and reading it back.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis.presence import analytics, graph_sheet, history
from jarvis.presence.charts import PALETTE, line_chart
from jarvis.presence.report import SiteInfo
from jarvis.presence.youtube import Channel, Video
from jarvis.presence.website import fetch_site

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
BASE = NOW.timestamp()


# -- chart engine ----------------------------------------------------------


class TestLineChart:
    def _chart(self, series, **kwargs):
        return line_chart(series, **kwargs)

    def test_produces_an_svg_element(self):
        svg = self._chart([("A", [(0, 1), (1, 2)])], title="T")
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        assert 'xmlns="http://www.w3.org/2000/svg"' in svg

    def test_title_is_escaped(self):
        svg = self._chart([("A", [(0, 1)])], title='<script>alert(1)</script>')
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg

    def test_none_values_draw_gaps_not_zeroes(self):
        """A missing data point must not be plotted as zero.

        Plotting a gap as zero manufactures a drop that never happened, which
        is the one thing a trend chart must not do.
        """
        svg = self._chart([("A", [(0, 10), (1, None), (2, 20)])])
        points = svg.split('points="')[1].split('"')[0]
        # The gap breaks the polyline into two segments.
        assert " " in points.strip()

    def test_empty_series_gives_a_placeholder(self):
        svg = self._chart([], title="Empty")
        assert "<svg" in svg
        assert "Empty" in svg

    def test_no_points_at_all(self):
        svg = self._chart([("A", [])])
        assert "<svg" in svg

    def test_multiple_series_get_distinct_colours(self):
        series = [(f"s{i}", [(0, i), (1, i + 1)]) for i in range(len(PALETTE))]
        svg = self._chart(series)
        for colour in PALETTE:
            assert colour in svg

    def test_legend_names_appear(self):
        svg = self._chart([("My Channel", [(0, 1), (1, 2)])])
        assert "My Channel" in svg

    def test_y_axis_is_labelled(self):
        svg = self._chart([("A", [(0, 1), (1, 2)])], y_label="views")
        assert "views" in svg

    def test_tooltips_are_attached_to_points(self):
        svg = self._chart([("A", [(0, 42), (1, 84)])])
        assert "<title>" in svg
        assert "42" in svg

    def test_polyline_points_are_space_separated(self):
        """The points attribute must be a space-separated list.

        Joining them without a separator produces `64.0,236.0223.0,236.0`,
        which is invalid SVG: the browser cannot parse it and draws no line at
        all, leaving a chart of floating dots that reads as empty. This is the
        regression test for exactly that bug.
        """
        svg = self._chart([("A", [(0, 10), (1, 20), (2, 30)])])
        points = svg.split('points="')[1].split('"')[0]
        pairs = points.strip().split(" ")
        assert len(pairs) == 3
        for pair in pairs:
            x, y = pair.split(",")
            assert float(x) > 0 and float(y) > 0


# -- website metrics -------------------------------------------------------


class TestSiteMetrics:
    def test_new_fields_default_to_none(self):
        site = SiteInfo(url="https://x.test", reachable=False, title="", text="")
        assert site.response_time_ms is None
        assert site.page_size_bytes is None
        assert site.word_count is None
        assert site.ssl_expires is None

    def test_fetch_site_populates_the_metrics(self):
        """A real fetch populates every metric, not just reachability."""
        site = fetch_site("https://example.com", probe=False)
        assert site.reachable is True
        assert site.response_time_ms is not None and site.response_time_ms > 0
        assert site.page_size_bytes is not None and site.page_size_bytes > 0
        assert site.word_count is not None and site.word_count > 0


# -- history: site metrics -------------------------------------------------


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "history.db"
    monkeypatch.setattr(history, "DB_PATH", path)
    monkeypatch.setattr(analytics.history, "DB_PATH", path)
    return path


def _site(up: bool = True, ms: int = 200, size: int = 5000, words: int = 300) -> SiteInfo:
    return SiteInfo(
        url="https://a.test",
        reachable=up,
        title="A",
        text="x",
        response_time_ms=ms if up else None,
        page_size_bytes=size if up else None,
        word_count=words if up else None,
    )


class TestSiteMetricHistory:
    def test_round_trips(self, db):
        history.record(sites=[_site(ms=200, size=5000, words=300)])
        history.record(sites=[_site(ms=400, size=6000, words=350)])

        metrics = history.site_metrics("https://a.test")
        assert len(metrics) == 2
        assert metrics[0][1] == 200
        assert metrics[-1][1] == 400
        assert metrics[-1][3] == 350

    def test_window_filters_old_points(self, db):
        history.record(sites=[_site(ms=100)], taken_at=NOW - timedelta(days=60))
        history.record(sites=[_site(ms=200)], taken_at=NOW)

        assert len(history.site_metrics("https://a.test", days=30)) == 1
        assert len(history.site_metrics("https://a.test", days=90)) == 2

    def test_unreachable_site_has_no_timing(self, db):
        history.record(sites=[_site(up=False)])
        metrics = history.site_metrics("https://a.test")
        assert metrics[0][1] is None


# -- graph sheet -----------------------------------------------------------


class TestGraphSheet:
    def test_no_history_says_so(self, db):
        html = graph_sheet.render_graph_sheet()
        assert "<!DOCTYPE html>" in html
        assert "No history recorded yet" in html
        assert "<svg" not in html

    def test_produces_a_complete_document(self, db):
        history.record(sites=[_site()], channels=[
            Channel(
                name="C", channel_id="UCc", url="u", joined=NOW,
                videos=[Video(
                    title="V", video_id="v1", url="u1", published=NOW,
                    updated=NOW, description="", views=10,
                )],
            )
        ])

        html = graph_sheet.render_graph_sheet()
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "<style>" in html
        assert "YouTube channels" in html
        assert "Websites" in html

    def test_contains_charts_when_history_exists(self, db):
        history.record(sites=[_site()], channels=[
            Channel(
                name="C", channel_id="UCc", url="u", joined=NOW,
                videos=[Video(
                    title="V", video_id="v1", url="u1", published=NOW,
                    updated=NOW, description="", views=10,
                )],
            )
        ])
        history.record(sites=[_site()], channels=[
            Channel(
                name="C", channel_id="UCc", url="u", joined=NOW,
                videos=[Video(
                    title="V", video_id="v1", url="u1", published=NOW,
                    updated=NOW, description="", views=20,
                )],
            )
        ])

        html = graph_sheet.render_graph_sheet()
        assert html.count("<svg") >= 3
        assert "<polyline" in html

    def test_makes_no_external_requests(self, db):
        """The sheet must be openable offline with nothing installed."""
        history.record(sites=[_site()])
        html = graph_sheet.render_graph_sheet()
        assert "<script" not in html.lower()
        assert "<link" not in html
        assert "<img" not in html
        assert "url(" not in html

    def test_video_titles_are_used_not_ids(self, db):
        history.record(sites=[], channels=[
            Channel(
                name="C", channel_id="UCc", url="u", joined=NOW,
                videos=[Video(
                    title="My Great Video", video_id="abc123", url="u1",
                    published=NOW, updated=NOW, description="", views=10,
                )],
            )
        ])
        history.record(sites=[], channels=[
            Channel(
                name="C", channel_id="UCc", url="u", joined=NOW,
                videos=[Video(
                    title="My Great Video", video_id="abc123", url="u1",
                    published=NOW, updated=NOW, description="", views=15,
                )],
            )
        ])

        html = graph_sheet.render_graph_sheet()
        assert "My Great Video" in html
        assert "abc123" not in html
