"""Tests for presence analytics — the trend layer over stored snapshots.

The history is built synthetically so the arithmetic is testable without
waiting for real days to pass. Each test inserts a known series of snapshots
and asserts the analytics read it back correctly.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis.presence import analytics, history
from jarvis.presence.report import SiteInfo
from jarvis.presence.youtube import Channel, Video

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
CHANNEL_ID = "UCtest"


@pytest.fixture
def db(state_dir):
    """The history database, inside the test's temporary state directory.

    `state_dir` redirects `paths.STATE_DIR`, which `history` reads per call —
    so the database follows the fixture instead of being pinned by hand.
    """
    return state_dir / "presence-history.db"


def _video(video_id: str, title: str, views: int, days_ago: int = 30) -> Video:
    published = NOW - timedelta(days=days_ago)
    return Video(
        title=title,
        video_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        published=published,
        updated=published,
        description="",
        views=views,
    )


def _channel(videos: list[Video]) -> Channel:
    return Channel(
        name="Test Channel",
        channel_id=CHANNEL_ID,
        url="https://www.youtube.com/channel/" + CHANNEL_ID,
        joined=NOW - timedelta(days=400),
        videos=videos,
    )


def _record(days_ago: int, videos: list[Video], *, up: bool = True) -> None:
    """Record a snapshot as it would have looked `days_ago` days back."""
    history.record(
        sites=[SiteInfo(
            url="https://a.test", reachable=up, title="A", text="x"
        )],
        channels=[_channel(videos)],
        taken_at=NOW - timedelta(days=days_ago),
    )


# -- with no history -------------------------------------------------------


class TestEmpty:
    def test_says_so_rather_than_printing_zeros(self, db):
        text = analytics.render_analytics()
        assert "No history recorded yet" in text

    def test_no_history_does_not_crash(self, db):
        assert history.snapshot_count() == 0
        assert history.date_range() == (None, None)


# -- with history ----------------------------------------------------------


class TestTrends:
    def test_total_views_growth_is_reported(self, db):
        _record(10, [_video("v1", "One", 100), _video("v2", "Two", 50)])
        _record(5, [_video("v1", "One", 150), _video("v2", "Two", 50)])
        _record(0, [_video("v1", "One", 200), _video("v2", "Two", 50)])

        text = analytics.render_analytics(days=30)
        assert "150 → 250" in text
        assert "+100" in text

    def test_flat_views_are_called_flat(self, db):
        _record(5, [_video("v1", "One", 100)])
        _record(0, [_video("v1", "One", 100)])

        text = analytics.render_analytics(days=30)
        assert "unchanged" in text

    def test_per_video_growth_is_listed(self, db):
        _record(5, [_video("v1", "Growing", 100), _video("v2", "Stuck", 40)])
        _record(0, [_video("v1", "Growing", 160), _video("v2", "Stuck", 40)])

        text = analytics.render_analytics(days=30)
        assert "Growing: 100 → 160 (+60" in text
        assert "Stuck: 40 (flat)" in text

    def test_biggest_gainer_is_listed_first(self, db):
        _record(5, [_video("v1", "Small", 100), _video("v2", "Big", 100)])
        _record(0, [_video("v1", "Small", 110), _video("v2", "Big", 300)])

        text = analytics.render_analytics(days=30)
        assert text.index("Big:") < text.index("Small:")

    def test_upload_count_in_period(self, db):
        _record(10, [_video("v1", "One", 10)])
        _record(0, [_video("v1", "One", 10), _video("v2", "Two", 5)])

        text = analytics.render_analytics(days=30)
        assert "Uploads in period: 1" in text

    def test_no_new_uploads_is_reported(self, db):
        _record(5, [_video("v1", "One", 10)])
        _record(0, [_video("v1", "One", 10)])

        text = analytics.render_analytics(days=30)
        assert "Uploads in period: 0" in text


class TestUptime:
    def test_full_uptime(self, db):
        _record(5, [_video("v1", "One", 10)], up=True)
        _record(0, [_video("v1", "One", 10)], up=True)

        text = analytics.render_analytics(days=30)
        assert "100.0%" in text
        assert "up throughout" in text

    def test_partial_uptime_is_flagged(self, db):
        _record(5, [_video("v1", "One", 10)], up=True)
        _record(0, [_video("v1", "One", 10)], up=False)

        text = analytics.render_analytics(days=30)
        assert "50.0%" in text
        assert "frequently down" in text


class TestWindow:
    def test_old_snapshots_fall_outside_the_window(self, db):
        _record(60, [_video("v1", "One", 100)])
        _record(0, [_video("v1", "One", 200)])

        # Over 30 days only the recent snapshot counts: no trend, one point.
        text = analytics.render_analytics(days=30)
        assert "one snapshot so far" in text

    def test_wider_window_includes_the_trend(self, db):
        _record(60, [_video("v1", "One", 100)])
        _record(0, [_video("v1", "One", 200)])

        text = analytics.render_analytics(days=90)
        assert "100 → 200" in text


class TestTitles:
    def test_video_titles_come_from_the_latest_snapshot(self, db):
        _record(5, [_video("v1", "Old Title", 10)])
        _record(0, [_video("v1", "New Title", 20)])

        titles = history.video_titles(CHANNEL_ID)
        assert titles["v1"] == "New Title"

    def test_channel_names_are_recalled(self, db):
        _record(0, [_video("v1", "One", 10)])
        names = history.channel_names()
        assert names[CHANNEL_ID] == "Test Channel"


# -- per-day traffic --------------------------------------------------------


class TestDailyReport:
    def test_says_so_when_there_is_no_history(self, db):
        assert "No history recorded yet" in analytics.render_daily()

    def test_a_single_snapshot_is_a_baseline_not_a_day(self, db):
        _record(0, [_video("v1", "One", 100)])

        text = analytics.render_daily(days=30)
        assert "not a day of traffic" in text

    def test_growth_is_reported_per_day(self, db):
        _record(2, [_video("v1", "One", 100)])
        _record(0, [_video("v1", "One", 160)])

        text = analytics.render_daily(days=30)
        assert "60 in total" in text
        assert "30.0/day" in text

    def test_a_video_first_seen_in_the_window_is_named_not_dropped(self, db):
        """A new upload has one sighting, so it cannot be a day of traffic —
        but it is the biggest event in the window and must still be visible."""
        _record(5, [_video("v1", "Old", 100)])
        _record(0, [_video("v1", "Old", 100), _video("v2", "Brand new", 40)])

        text = analytics.render_daily(days=30)
        assert "Brand new" in text
        assert "40 views at first sighting" in text
        # It must not be smuggled into the day series as if it were measured.
        assert "40/day" not in text
        assert "none recorded" in text

    def test_a_flat_window_says_none_rather_than_busiest_zero(self, db):
        _record(2, [_video("v1", "One", 100)])
        _record(0, [_video("v1", "One", 100)])

        text = analytics.render_daily(days=30)
        assert "none recorded" in text
        assert "Busiest day" not in text

    def test_websites_without_a_traffic_source_say_so(self, db):
        _record(0, [_video("v1", "One", 10)])

        text = analytics.render_daily(days=30)
        assert "no traffic source is configured" in text
        # And it must not invent a zero to fill the gap.
        assert "0 visitors" not in text

