"""Tests for the daily-traffic analytics — views and visitors per day.

The arithmetic here is the point: a cumulative view count is a number, and the
only way to answer "how many people used this today" is to difference it
against the last snapshot and divide by the time between them. These tests
pin that arithmetic, including the cases that are easy to get wrong (a
snapshot pair less than a day apart, a zero-length window, and the first
snapshot of a new video, which cannot be attributed to a day at all).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jarvis.presence.daily import (
    daily_channel_views,
    daily_video_views,
    video_pace,
)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def _pts(views: list[int], step_days: int = 1, start: datetime = NOW) -> list[tuple[datetime, int]]:
    """Points ordered oldest first, the way `history.channel_video_views` returns them."""
    span = step_days * (len(views) - 1)
    return [
        (start - timedelta(days=span - step_days * i), views[i])
        for i in range(len(views))
    ]


# -- channel-level days -----------------------------------------------------


class TestDailyChannelViews:
    def test_a_daily_series_with_no_growth_is_all_zeros(self):
        pts = _pts([100, 100, 100], step_days=1)
        days = daily_channel_views({"v1": pts})
        assert [views for _, views in days] == [0, 0]
        assert len(days) == 2

    def test_growth_is_attributed_to_the_day_it_happened(self):
        pts = _pts([100, 130, 130], step_days=1)
        days = daily_channel_views({"v1": pts})
        assert days[0][1] == 30  # 100 -> 130
        assert days[1][1] == 0

    def test_two_videos_on_the_same_day_are_summed(self):
        days = daily_channel_views({
            "v1": _pts([100, 110]),
            "v2": _pts([50, 60]),
        })
        assert len(days) == 1
        assert days[0][1] == 20

    def test_videos_published_mid_window_do_not_invent_traffic(self):
        """A video absent from the first snapshot contributes nothing that day."""
        v1 = _pts([100, 120])
        v2 = [(NOW - timedelta(days=1), 5), (NOW, 8)]
        days = daily_channel_views({"v1": v1, "v2": v2})
        assert len(days) == 1
        assert days[0][1] == 23  # 20 from v1 + 3 from v2, not 20 + 8

    def test_a_single_snapshot_has_no_day_to_report(self):
        assert daily_channel_views({"v1": _pts([42])}) == []

    def test_empty_history_is_empty(self):
        assert daily_channel_views({}) == []

    def test_views_never_go_backwards(self):
        """A correction in the source data must not report negative traffic."""
        pts = _pts([120, 100])
        days = daily_channel_views({"v1": pts})
        assert days[0][1] == 0


# -- video-level pace -------------------------------------------------------


class TestDailyVideoViews:
    def test_a_video_flat_over_two_days_reports_no_growth(self):
        days = daily_video_views(_pts([50, 50, 50]))
        assert [views for _, views in days] == [0, 0]

    def test_a_video_growing_by_ten_a_day_reports_ten(self):
        days = daily_video_views(_pts([50, 60, 70]))
        assert [views for _, views in days] == [10, 10]

    def test_a_video_with_one_snapshot_reports_nothing(self):
        assert daily_video_views(_pts([7])) == []


class TestVideoPace:
    def test_pace_is_growth_over_the_observed_window(self):
        # +60 views over 30 days = 2.0/day
        pts = _pts([100, 160], step_days=30)
        assert video_pace(pts) == 2.0

    def test_pace_is_none_without_two_points(self):
        assert video_pace(_pts([100])) is None
        assert video_pace([]) is None

    def test_pace_is_none_when_the_window_has_no_length(self):
        """Two snapshots at the same instant cannot yield a rate."""
        same = NOW
        assert video_pace([(same, 10), (same, 20)]) is None

    def test_a_flat_video_has_a_pace_of_zero_not_none(self):
        assert video_pace(_pts([10, 10], step_days=5)) == 0.0

    def test_pace_can_be_negative_when_views_are_corrected_down(self):
        pts = _pts([100, 40], step_days=10)
        assert video_pace(pts) == -6.0
