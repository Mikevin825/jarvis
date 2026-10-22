"""The graph sheet — every presence trend on one page.

This is the deliverable the user actually opens: a single self-contained HTML
file with inline SVG charts and no external requests. It works offline, it
works on a phone, and it can be archived — a snapshot of the business's online
health at a moment in time.

The charts come from `charts.py` and the data from `history.py`, so the sheet
is a pure function of stored history. Nothing here fetches anything.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import history
from .charts import line_chart

# How many per-video lines to draw on one chart. More than this and the legend
# becomes unreadable; the top few are the ones that matter anyway.
MAX_VIDEO_SERIES = 5

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  background: #f9fafb; color: #111827; line-height: 1.5;
}
.wrap { max-width: 820px; margin: 0 auto; }
header { margin-bottom: 24px; }
h1 { font-size: 22px; margin: 0 0 4px; }
.sub { color: #6b7280; font-size: 13px; }
section {
  background: #fff; border: 1px solid #e5e7eb; border-radius: 10px;
  padding: 20px; margin-bottom: 20px;
}
h2 { font-size: 16px; margin: 0 0 4px; }
h3 { font-size: 13px; margin: 20px 0 8px; color: #374151; font-weight: 600; }
.chart { margin: 12px 0 4px; overflow-x: auto; }
.chart svg { max-width: 100%; height: auto; display: block; }
table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 8px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #f3f4f6; }
th { color: #6b7280; font-weight: 600; font-size: 11px; text-transform: uppercase; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.empty { color: #9ca3af; font-size: 13px; font-style: italic; }
footer { color: #9ca3af; font-size: 11px; margin-top: 8px; text-align: center; }
"""


def _date_label(epoch: float) -> str:
    """Short date for an x-axis tick."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%d %b")


def _epoch(moment: datetime) -> float:
    return moment.timestamp()


def _insufficient(what: str, have: int) -> str:
    """An honest placeholder when there is no trend to draw.

    A chart with a single point is a dot floating in white space, which reads
    as a broken chart. Saying "one snapshot recorded" is both more truthful
    and more useful — it tells the user what to do next.
    """
    return (
        f"<p class='empty'>{what}: {have} snapshot(s) recorded — "
        "a trend needs at least two.</p>"
    )


def _channel_total_views_chart(channel_id: str, name: str, days: int) -> str:
    """One line per channel: total views over time."""
    totals = history.channel_totals(channel_id, days=days)
    if len(totals) < 2:
        return _insufficient(name, len(totals))
    points = [(_epoch(when), float(total)) for when, _count, total in totals]
    return line_chart(
        [(name, points)],
        title=f"{name} — total views",
        y_label="views",
        x_formatter=_date_label,
    )


def _channel_per_video_chart(channel_id: str, name: str, days: int) -> str:
    """One line per video: how each video's views grew.

    This is the chart that answers "which video is working", and it is only
    possible because history stores per-video views rather than a channel
    total.
    """
    video_views = history.channel_video_views(channel_id, days=days)
    titles = history.video_titles(channel_id)
    if not video_views:
        return _insufficient(name, 0)

    # Rank by most recent views and keep the top few, so the legend stays
    # readable instead of becoming a wall of colour.
    ranked = sorted(
        video_views.items(),
        key=lambda item: item[1][-1][1] if item[1] else 0,
        reverse=True,
    )[:MAX_VIDEO_SERIES]

    series = []
    for video_id, points in ranked:
        label = titles.get(video_id) or video_id
        series.append((label, [(_epoch(when), float(views)) for when, views in points]))

    return line_chart(
        series,
        title=f"{name} — views by video",
        y_label="views",
        x_formatter=_date_label,
    )


def _site_response_chart(url: str, name: str, days: int) -> str:
    metrics = history.site_metrics(url, days=days)
    points = [
        (_epoch(when), float(ms))
        for when, ms, _size, _words in metrics
        if ms is not None
    ]
    if len(points) < 2:
        return _insufficient(name, len(points))
    return line_chart(
        [(name, points)],
        title=f"{name} — response time",
        y_label="ms",
        x_formatter=_date_label,
    )


def _site_size_chart(url: str, name: str, days: int) -> str:
    metrics = history.site_metrics(url, days=days)
    points = [
        (_epoch(when), float(size))
        for when, _ms, size, _words in metrics
        if size is not None
    ]
    if len(points) < 2:
        return _insufficient(name, len(points))
    return line_chart(
        [(name, points)],
        title=f"{name} — page size",
        y_label="bytes",
        x_formatter=_date_label,
    )


def _render_chart_or_note(chart: str) -> str:
    """Wrap an SVG chart, or pass through an 'insufficient data' note.

    The chart functions return either a complete `<svg>` element or an HTML
    note explaining that there is not enough history yet. Both are ready to
    drop into the page; they just need different wrappers.
    """
    if not chart:
        return ""
    if chart.startswith("<svg"):
        return f"<div class='chart'>{chart}</div>"
    return chart


def _summary_table(days: int) -> str:
    """The current numbers, so the sheet is useful even with no history."""
    rows = []
    for channel_id in history.tracked_channels():
        name = history.channel_names().get(channel_id) or channel_id
        totals = history.channel_totals(channel_id, days=days)
        latest = totals[-1] if totals else None
        rows.append(
            f"<tr><td>{name}</td>"
            f"<td class='num'>{latest[1] if latest else 0}</td>"
            f"<td class='num'>{latest[2] if latest else 0:,}</td></tr>"
        )
    for url in history.tracked_sites():
        uptime, samples = history.site_uptime(url, days=days)
        pct = f"{uptime * 100:.1f}%" if samples else "—"
        rows.append(
            f"<tr><td>{url}</td><td class='num'>{pct}</td>"
            f"<td class='num'>{samples}</td></tr>"
        )
    if not rows:
        return ""
    return (
        "<table><thead><tr><th>Target</th><th>Latest</th><th>Views / checks</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def render_graph_sheet(days: int = 30) -> str:
    """Render the complete graph sheet as a self-contained HTML document."""
    total = history.snapshot_count()
    first, last = history.date_range()

    if total == 0:
        return _page(
            "Presence graph sheet",
            "<p class='empty'>No history recorded yet. The heartbeat check "
            "stores a snapshot each day; trends appear once there is data.</p>",
            generated=datetime.now(timezone.utc),
        )

    parts = [
        "<section><h2>YouTube channels</h2>",
        "<p class='sub'>Total views and per-video growth over the period.</p>",
    ]
    for channel_id in history.tracked_channels():
        name = history.channel_names().get(channel_id) or channel_id
        parts.append(f"<h3>{name}</h3>")
        for chart in (
            _channel_total_views_chart(channel_id, name, days),
            _channel_per_video_chart(channel_id, name, days),
        ):
            parts.append(_render_chart_or_note(chart))
    parts.append("</section>")

    parts.append("<section><h2>Websites</h2>")
    parts.append("<p class='sub'>Response time and page size over the period.</p>")
    for url in history.tracked_sites():
        parts.append(f"<h3>{url}</h3>")
        for chart in (
            _site_response_chart(url, url, days),
            _site_size_chart(url, url, days),
        ):
            parts.append(_render_chart_or_note(chart))
    parts.append("</section>")

    table = _summary_table(days)
    if table:
        parts.append(f"<section><h2>Current</h2>{table}</section>")

    span = ""
    if first and last:
        span = f"{first.strftime('%d %b %Y')} → {last.strftime('%d %b %Y')}"
    return _page(
        "Presence graph sheet",
        "".join(parts),
        generated=datetime.now(timezone.utc),
        subtitle=f"{total} snapshot(s) · {span} · {days}-day window",
    )


def _page(title: str, body: str, *, generated: datetime, subtitle: str = "") -> str:
    """Wrap chart sections in a complete HTML document."""
    sub = f"<p class='sub'>{subtitle}</p>" if subtitle else ""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title><style>{_CSS}</style></head>"
        f"<body><div class='wrap'><header><h1>{title}</h1>{sub}</header>"
        f"{body}"
        f"<footer>Generated {generated.strftime('%d %b %Y, %H:%M')} · "
        "JARVIS presence analytics</footer>"
        "</div></body></html>"
    )
