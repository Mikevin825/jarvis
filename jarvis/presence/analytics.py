"""Presence analytics — the trends a snapshot cannot show.

`report.py` answers "where do things stand". This answers "which way are they
moving", and it is only possible because `history.py` has been keeping score.

The numbers here are deliberately plain. A channel owner does not need a chart
to decide whether to post more; they need to know whether the last video grew,
how fast, and whether that is better or worse than the one before it. So the
output leads with the few figures that change a decision and leaves the rest in
a table.

Everything is computed from stored snapshots, so it works offline and it is
reproducible — the same history always yields the same analytics.

`render_analytics` is the growth report. `render_daily` is the per-day report:
the same history read at day granularity, which is what "how many people used
this today" actually asks. The arithmetic lives in `daily.py`, kept pure so it
can be tested without a database.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import daily, history

# Below this many snapshots there is no trend to speak of, only a data point.
MIN_SNAPSHOTS_FOR_TREND = 2


def _pct_change(before: int, after: int) -> float | None:
    """Percentage growth, or None when the starting value was zero.

    A video that went 0 → 50 views grew by an infinite percentage, which is a
    true and useless thing to say. Reporting it as "new" is more honest.
    """
    if before <= 0:
        return None
    return (after - before) / before * 100.0


def _views_per_day(points: list[tuple[datetime, int]]) -> float | None:
    """Average daily growth over the observed window, or None if unmeasurable."""
    if len(points) < MIN_SNAPSHOTS_FOR_TREND:
        return None
    first_when, first_views = points[0]
    last_when, last_views = points[-1]
    days = (last_when - first_when).total_seconds() / 86400.0
    if days <= 0:
        return None
    return (last_views - first_views) / days


def _channel_analytics(channel_id: str, name: str, days: int) -> list[str]:
    """Trend lines for one channel. Returns rendered lines."""
    lines: list[str] = [f"YouTube: {name}"]

    video_views = history.channel_video_views(channel_id, days=days)
    totals = history.channel_totals(channel_id, days=days)
    titles = history.video_titles(channel_id)

    if not totals:
        lines.append("  No history recorded yet.")
        return lines

    # -- the headline: is the total moving? --------------------------------
    if len(totals) >= MIN_SNAPSHOTS_FOR_TREND:
        first_when, first_count, first_total = totals[0]
        last_when, last_count, last_total = totals[-1]
        span = (last_when - first_when).days

        if last_total > first_total:
            growth = last_total - first_total
            per_day = growth / span if span > 0 else growth
            lines.append(
                f"  Total views: {first_total:,} → {last_total:,} "
                f"(+{growth:,}, about {per_day:.1f}/day over {span} days)"
            )
        elif last_total < first_total:
            lines.append(
                f"  Total views: {first_total:,} → {last_total:,} "
                f"(fell {first_total - last_total:,})"
            )
        else:
            lines.append(
                f"  Total views: {last_total:,} — unchanged across "
                f"{len(totals)} snapshots over {span} days."
            )
    else:
        lines.append(f"  Total views: {totals[0][2]:,} (one snapshot so far).")

    # -- per-video growth --------------------------------------------------
    if video_views:
        rows = []
        for video_id, points in video_views.items():
            if len(points) < MIN_SNAPSHOTS_FOR_TREND:
                continue
            first_when, first_views = points[0]
            last_when, last_views = points[-1]
            span = (last_when - first_when).days
            delta = last_views - first_views
            per_day = delta / span if span > 0 else None
            rows.append((video_id, first_views, last_views, delta, per_day, points))

        if rows:
            # Biggest absolute gainer first — the one worth paying attention to.
            rows.sort(key=lambda r: r[3], reverse=True)
            lines.append("")
            lines.append("  Views by video:")
            for video_id, first_v, last_v, delta, per_day, points in rows[:6]:
                title = titles.get(video_id) or video_id
                if delta > 0:
                    rate = f", {per_day:.1f}/day" if per_day is not None else ""
                    lines.append(f"    {title}: {first_v:,} → {last_v:,} (+{delta:,}{rate})")
                elif delta < 0:
                    lines.append(f"    {title}: {first_v:,} → {last_v:,} ({delta:,})")
                else:
                    lines.append(f"    {title}: {last_v:,} (flat)")

    # -- upload activity ---------------------------------------------------
    if len(totals) >= MIN_SNAPSHOTS_FOR_TREND:
        first_count = totals[0][1]
        last_count = totals[-1][1]
        new_uploads = last_count - first_count
        span = (totals[-1][0] - totals[0][0]).days
        if new_uploads > 0:
            per_week = new_uploads / (span / 7) if span > 0 else new_uploads
            lines.append(
                f"\n  Uploads in period: {new_uploads} "
                f"(about {per_week:.1f}/week)"
            )
        else:
            lines.append(f"\n  Uploads in period: 0 (still {last_count} total)")

    return lines


def _site_analytics(url: str, name: str, days: int) -> list[str]:
    """Uptime and performance trends for one website."""
    lines: list[str] = [f"Website: {name or url}"]
    uptime, samples = history.site_uptime(url, days=days)

    if samples == 0:
        lines.append("  No history recorded yet.")
        return lines

    pct = uptime * 100.0
    if pct >= 99.9:
        verdict = "up throughout"
    elif pct >= 95:
        verdict = "mostly up"
    elif pct >= 80:
        verdict = "flaky"
    else:
        verdict = "frequently down"
    lines.append(
        f"  Uptime: {pct:.1f}% over {samples} check(s) — {verdict}"
    )

    # Response time trend
    metrics = history.site_metrics(url, days=days)
    if len(metrics) >= MIN_SNAPSHOTS_FOR_TREND:
        times = [m[1] for m in metrics if m[1] is not None]
        if times:
            lines.append(
                f"  Response: {times[0]} ms → {times[-1]} ms "
                f"(avg {int(sum(times) / len(times))} ms)"
            )
        else:
            lines.append("  Response: n/a")
        sizes = [m[2] for m in metrics if m[2] is not None]
        if sizes:
            delta = sizes[-1] - sizes[0]
            direction = "grew" if delta > 0 else "shrank" if delta < 0 else "unchanged"
            lines.append(
                f"  Page size: {sizes[0]:,} B → {sizes[-1]:,} B ({direction} {abs(delta):,} B)"
            )
        words = [m[3] for m in metrics if m[3] is not None]
        if words:
            lines.append(f"  Words: {words[0]:,} → {words[-1]:,}")
    return lines


def render_analytics(days: int = 30) -> str:
    """Render the analytics report for the given window.

    With no history at all this says so plainly rather than printing zeros —
    a report full of 0% uptime and "no change" is worse than no report.
    """
    total = history.snapshot_count()
    if total == 0:
        return (
            "Presence analytics\n"
            "No history recorded yet.\n\n"
            "The heartbeat check stores a snapshot each time it runs, so trends "
            "appear after a few days. Run `--status-report` to record one now."
        )

    first, last = history.date_range()
    lines: list[str] = [
        f"Presence analytics — last {days} days",
        f"History: {total} snapshot(s), "
        f"{_fmt(first)} → {_fmt(last)}",
        "",
    ]

    channels = history.tracked_channels()
    sites = history.tracked_sites()
    names = history.channel_names()

    if not channels and not sites:
        lines.append("Nothing is being tracked.")
        return "\n".join(lines)

    for channel_id in channels:
        name = names.get(channel_id) or channel_id
        lines.extend(_channel_analytics(channel_id, name, days))
        lines.append("")

    for url in sites:
        lines.extend(_site_analytics(url, url, days))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# -- per-day traffic ---------------------------------------------------------


def _daily_channel_lines(channel_id: str, name: str, days: int) -> list[str]:
    """Per-day views for one channel, plus each video's daily rate."""
    lines: list[str] = [f"YouTube: {name}"]

    # include_baseline: without the snapshot before the window the first day is
    # not measurable at all (see history.channel_video_views).
    video_views = history.channel_video_views(channel_id, days=days, include_baseline=True)
    day_series = daily.daily_channel_views(video_views)

    if not day_series:
        lines.append("  No per-day traffic yet — one snapshot is not a day of traffic.")
        return lines

    total = daily.total_in_window(day_series)
    average = daily.average_per_day(day_series)
    if total == 0:
        # Saying "busiest day: 0" is worse than saying there was nothing: it
        # reads as a measurement of zero rather than as an absence of traffic.
        lines.append(
            f"  Views per day: none recorded across {len(day_series)} day(s) "
            "in this window."
        )
    else:
        lines.append(
            f"  Views per day: {total:,} in total, {average:.1f}/day on average "
            f"over {len(day_series)} day(s)"
        )
        best = daily.best_day(day_series)
        quiet = daily.quietest_day(day_series)
        if best is not None:
            lines.append(f"  Busiest day: {_fmt(best[0])} — {best[1]:,}")
        if quiet is not None:
            lines.append(f"  Slowest day: {_fmt(quiet[0])} — {quiet[1]:,}")

    lines.append("")
    lines.append("  Day by day:")
    lines.append(
        "    " + " · ".join(f"{when.strftime('%d %b')}: {views:,}" for when, views in day_series)
    )

    # Per-video rate: which upload is actually pulling its weight.
    rows: list[tuple[str, float]] = []
    for video_id, points in video_views.items():
        pace = daily.video_pace(points)
        if pace is not None:
            rows.append((video_id, pace))
    if rows:
        rows.sort(key=lambda row: row[1], reverse=True)
        titles = history.video_titles(channel_id)
        lines.append("")
        lines.append("  Views per day, by video:")
        for video_id, pace in rows[:6]:
            title = titles.get(video_id) or video_id
            lines.append(f"    {title}: {pace:.1f}/day")

    # A video with a single sighting has nothing to be differenced against, so
    # it cannot be turned into a day of traffic. Dropping it silently is the
    # wrong call though: the first sighting is often the biggest event in the
    # window. It is named instead, with the count at first sighting, and the
    # day series stays strictly comparable.
    first_sightings = [
        (video_id, points[0][1])
        for video_id, points in video_views.items()
        if len(points) == 1
    ]
    if first_sightings:
        titles = history.video_titles(channel_id)
        lines.append("")
        lines.append("  First seen in this window — not yet measurable per day:")
        for video_id, views in first_sightings:
            title = titles.get(video_id) or video_id
            lines.append(f"    {title}: {views:,} views at first sighting")

    return lines


def _daily_site_lines(url: str, days: int) -> list[str]:
    """Per-day visitors for one website.

    The honest answer today is that there is nothing to report: neither site
    carries an analytics snippet, so no visitor count exists to read. Saying so
    beats printing a zero, which reads as "nobody visited" rather than "nobody
    counted".
    """
    lines: list[str] = [f"Website: {url}"]
    lines.append(
        "  Visitors per day: no traffic source is configured for this site, so "
        "there is no visitor count to report."
    )
    lines.append(
        "  Add an analytics snippet to the site (or point JARVIS at one) and "
        "this section will fill in."
    )
    return lines


def render_daily(days: int = 30) -> str:
    """The per-day report — traffic at day granularity.

    Views, not people: YouTube's feed reports a cumulative view count and cannot
    say how many distinct viewers there were, so "views/day" is the honest
    figure. The same limit applies to any website source that counts visits.
    """
    total = history.snapshot_count()
    if total == 0:
        return (
            "Per-day traffic\n"
            "No history recorded yet.\n\n"
            "The heartbeat records a snapshot each run; a day of traffic needs "
            "two of them. Run `--status-report` to record one now."
        )

    first, last = history.date_range()
    lines: list[str] = [
        f"Per-day traffic — last {days} days",
        f"History: {total} snapshot(s), {_fmt(first)} → {_fmt(last)}",
        "",
        "Views, not people: YouTube counts views, so a day with 3 views may be "
        "3 people or 1 person watching 3 times.",
        "",
    ]

    channels = history.tracked_channels()
    sites = history.tracked_sites()
    names = history.channel_names()

    for channel_id in channels:
        lines.extend(_daily_channel_lines(channel_id, names.get(channel_id) or channel_id, days))
        lines.append("")

    for url in sites:
        lines.extend(_daily_site_lines(url, days))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _fmt(moment: datetime | None) -> str:
    return moment.strftime("%d %b %Y") if moment else "?"
