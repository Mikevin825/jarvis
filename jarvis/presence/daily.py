"""Daily traffic arithmetic — turning cumulative counts into per-day figures.

YouTube's feed reports a *cumulative* view count, and a website analytics source
reports cumulative visits. Neither says "how many today" on its own: that is the
difference between two snapshots divided by the time between them. This module
is that arithmetic, kept free of SQL and I/O so it can be tested directly.

Two judgement calls are worth stating, because both are easy to get wrong:

* **A drop in the source is clamped to zero, never reported as negative.** A
  view count can be corrected downward by YouTube; that is not "negative
  traffic", and a negative bar in a chart is a lie.
* **The first snapshot of a video invents nothing.** If a video is absent from
  the earlier snapshot, the day it appears cannot be split between "views it
  already had" and "views it gained", so it contributes nothing to that day.

The one thing this module cannot do is attribute a day to a snapshot that has
no predecessor. That is why `history` can include the last snapshot *before*
the window — without it the first day of every report would be silently lost.
"""

from __future__ import annotations

from datetime import datetime

# A view count that moves by less than this between two snapshots is noise from
# the source's own rounding, not traffic. Kept at zero: clamping is not the same
# as smoothing, and a one-view wobble is still a real view.
MIN_MEANINGFUL_DELTA = 0


def daily_video_views(points: list[tuple[datetime, int]]) -> list[tuple[datetime, int]]:
    """Per-interval traffic for one video.

    `points` is `(when, cumulative_views)` ordered oldest first, straight from
    `history.channel_video_views`. Each returned entry is attributed to the
    *later* snapshot's time, because that is when the growth was observed.

    A video with fewer than two snapshots has no interval to measure and
    returns nothing — a single data point is not a trend.
    """
    out: list[tuple[datetime, int]] = []
    for (earlier_when, earlier_views), (later_when, later_views) in zip(points, points[1:]):
        delta = later_views - earlier_views
        out.append((later_when, delta if delta > MIN_MEANINGFUL_DELTA else 0))
    return out


def daily_channel_views(
    video_views: dict[str, list[tuple[datetime, int]]],
) -> list[tuple[datetime, int]]:
    """Per-day traffic for a whole channel, summed across its videos.

    Videos are merged by the time their growth was observed, so a channel with
    several uploads reports one number per day rather than one series per video.
    A video that was not in the earlier snapshot simply contributes nothing to
    that day (see the module docstring).
    """
    merged: dict[datetime, int] = {}
    for points in video_views.values():
        for when, views in daily_video_views(points):
            merged[when] = merged.get(when, 0) + views
    return sorted(merged.items())


def video_pace(points: list[tuple[datetime, int]]) -> float | None:
    """Average views per day across the whole observed window, or None.

    None means "not measurable" — fewer than two snapshots, or two snapshots
    at the same instant. A flat video returns 0.0, which is a measurement, not a
    failure: the difference between "no growth" and "cannot tell" is the whole
    point of this figure.
    """
    if len(points) < 2:
        return None
    first_when, first_views = points[0]
    last_when, last_views = points[-1]
    days = (last_when - first_when).total_seconds() / 86400.0
    if days <= 0:
        return None
    return (last_views - first_views) / days


def total_in_window(days: list[tuple[datetime, int]]) -> int:
    """Traffic across the reported days. Zero when there is nothing to report."""
    return sum(views for _, views in days)


def average_per_day(days: list[tuple[datetime, int]]) -> float | None:
    """Mean traffic per reported day, or None with no days.

    Each entry is one snapshot interval, which is a day in practice because the
    heartbeat records daily. Dividing by the entry count rather than by the
    clock span is deliberate: with a gap in the history, the span would
    understate the rate by charging the missing days against real traffic.
    """
    if not days:
        return None
    return total_in_window(days) / len(days)


def best_day(days: list[tuple[datetime, int]]) -> tuple[datetime, int] | None:
    """The busiest day in the window, or None if there is nothing to report."""
    if not days:
        return None
    return max(days, key=lambda day: day[1])


def quietest_day(days: list[tuple[datetime, int]]) -> tuple[datetime, int] | None:
    """The slowest day in the window. Useful in the opposite direction: a run of
    zero-traffic days is the signal that a channel has stopped being watched."""
    if not days:
        return None
    return min(days, key=lambda day: day[1])
