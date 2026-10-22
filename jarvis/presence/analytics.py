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
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import history

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


def _fmt(moment: datetime | None) -> str:
    return moment.strftime("%d %b %Y") if moment else "?"
