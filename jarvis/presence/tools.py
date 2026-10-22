"""Presence tools — let JARVIS read the business's website and YouTube channel.

These wrap `jarvis.presence`, so the report the model sees is the same report
the CLI prints. The URLs come from config (`presence:`), which means JARVIS
knows what to check without being told each time — but either tool accepts an
explicit URL, so a one-off look at some other site still works.
"""

from __future__ import annotations

from ..tools.base import Tool, ToolError
from ..config import load_config, load_dotenv
from . import (
    YouTubeError,
    channel_summary,
    generate_status_report,
    render_analytics,
    site_summary,
)


def _settings() -> tuple[tuple, tuple]:
    """Read the configured presence targets, falling back to empty.

    Returns (websites, channels). Read per call so editing config.yaml takes
    effect without a restart.
    """
    try:
        load_dotenv()
        cfg = load_config()
        return cfg.presence.all_websites, cfg.presence.all_channels
    except Exception:  # noqa: BLE001 - a config problem must not kill the tool
        return (), ()


def check_website(url: str = "") -> str:
    """Fetch the business website and report what is on it and whether it works."""
    websites, _ = _settings()
    target = (url or "").strip() or (websites[0] if websites else "")
    if not target:
        raise ToolError(
            "No website is configured. Add `presence.website_url` to config.yaml, "
            "or give me a URL to check."
        )
    return site_summary(target)


def check_youtube_channel(channel: str = "") -> str:
    """Read a YouTube channel's recent uploads and cadence from its RSS feed."""
    _, channels = _settings()
    target = (channel or "").strip() or (channels[0] if channels else "")
    if not target:
        raise ToolError(
            "No YouTube channel is configured. Add `presence.youtube_channel` "
            "to config.yaml, or give me a channel to check."
        )
    try:
        return channel_summary(target)
    except YouTubeError as exc:
        raise ToolError(str(exc)) from exc


def business_status_report() -> str:
    """A full status report across every configured website and channel."""
    websites, channels = _settings()
    if not websites and not channels:
        raise ToolError(
            "Nothing is configured to report on. Add `presence.websites` and/or "
            "`presence.youtube_channels` to config.yaml."
        )
    return generate_status_report(websites=websites, channels=channels)


def record_presence() -> str:
    """Fetch every configured target and store a snapshot for the analytics.

    The heartbeat does this automatically each day; this is for building
    history on demand — run it a few times over a week and `--analytics` has
    something real to work with.
    """
    websites, channels = _settings()
    if not websites and not channels:
        raise ToolError(
            "Nothing is configured to record. Add `presence.websites` and/or "
            "`presence.youtube_channels` to config.yaml."
        )

    from .report import build_report
    from .history import record

    report = build_report(websites=websites, channels=channels)
    snapshot_id = record(sites=report.sites, channels=report.channels)

    return (
        f"Recorded snapshot #{snapshot_id}: "
        f"{len(report.sites)} site(s), {len(report.channels)} channel(s)."
    )


def presence_analytics(days: int = 30) -> str:
    """Trends over time — views growth, upload rate, site uptime.

    Needs history to exist. With less than two snapshots there is no trend to
    report, and the output says so rather than printing zeros.
    """
    return render_analytics(days=days)


def presence_graph_sheet(days: int = 30) -> str:
    """Generate the graph sheet — every trend as a chart on one HTML page.

    The file is written to reports/ and the path returned, so it can be opened
    directly. Self-contained: no external requests, works offline.
    """
    from ..paths import REPORTS_DIR
    from .graph_sheet import render_graph_sheet

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / "presence-graph-sheet.html"
    path.write_text(render_graph_sheet(days=days), encoding="utf-8")
    return f"Graph sheet written to {path}"


def build() -> list[Tool]:
    return [
        Tool(
            name="check_website",
            description=(
                "Use this to read the business website: what it offers, how it "
                "presents itself, and whether it is up. Also probes common "
                "pages like /pricing and /contact for broken links. Call it "
                "when the user asks about their site, their online presence, "
                "or whether their website is working."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "url": {
                        "type": "STRING",
                        "description": (
                            "Optional. A specific URL to check instead of the "
                            "configured business website."
                        ),
                    }
                },
            },
            func=check_website,
        ),
        Tool(
            name="check_youtube_channel",
            description=(
                "Use this to read a YouTube channel: its recent uploads, how "
                "often it posts, and how those videos are performing. Call it "
                "when the user asks about their channel, their uploads, or "
                "their content cadence."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "channel": {
                        "type": "STRING",
                        "description": (
                            "Optional. A channel (@handle or URL) to check "
                            "instead of the configured one."
                        ),
                    }
                },
            },
            func=check_youtube_channel,
        ),
        Tool(
            name="business_status_report",
            description=(
                "Use this for a full status report across the business's online "
                "presence — the website and the YouTube channel together, with "
                "anything wrong called out first. Call it when the user asks "
                "for a status check, a health check, or 'how is the business "
                "looking online'."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {},
                "required": [],
            },
            func=business_status_report,
        ),
        Tool(
            name="presence_analytics",
            description=(
                "Use this for trends over time rather than a snapshot: whether "
                "total views are growing, which videos gained the most, how "
                "often the channel is uploading, and each website's uptime "
                "percentage. Call it when the user asks about growth, "
                "momentum, trends, or 'how are we doing' over a period."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "days": {
                        "type": "INTEGER",
                        "description": (
                            "Optional. How many days of history to analyse. "
                            "Defaults to 30."
                        ),
                    },
                },
                "required": [],
            },
            func=presence_analytics,
        ),
        Tool(
            name="record_presence",
            description=(
                "Use this to store a snapshot of the current presence data for "
                "the analytics. The heartbeat does this automatically each "
                "day; call it to build history on demand."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {},
                "required": [],
            },
            func=record_presence,
        ),
        Tool(
            name="presence_graph_sheet",
            description=(
                "Use this to generate the graph sheet: an HTML page with a chart "
                "for every trend — total views, views by video, response time, "
                "and page size. Call it when the user asks for graphs, charts, "
                "a graph sheet, or to see the trends visually."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "days": {
                        "type": "INTEGER",
                        "description": (
                            "Optional. How many days of history to chart. "
                            "Defaults to 30."
                        ),
                    },
                },
                "required": [],
            },
            func=presence_graph_sheet,
        ),
    ]
