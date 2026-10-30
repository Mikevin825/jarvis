"""The business's online presence — website and YouTube channel, read together.

A status report is only worth having if it is cheap enough to ask for often, so
this module is deliberately boring:

* the website is read the same way `fetch_web` reads any page (one shared
  extractor, not a second parser);
* the YouTube channel comes from its public RSS feed — no API key, no
  scraping, nothing to revoke later;
* the report's numbers are computed, not asked of the model, so they are
  reproducible and testable.

`report.generate_status_report` is the entry point; the tools in
`jarvis/presence/tools.py` wrap it for the model, and `--status-report` on the
CLI runs it on demand.
"""

from __future__ import annotations

from .report import (
    StatusReport,
    build_report,
    generate_status_report,
    render_report,
)
from .analytics import render_analytics, render_daily
from .website import SiteInfo, fetch_site, site_summary
from .youtube import Channel, Video, YouTubeError, channel_summary, fetch_channel

__all__ = [
    "Channel",
    "SiteInfo",
    "StatusReport",
    "Video",
    "YouTubeError",
    "build_report",
    "channel_summary",
    "fetch_channel",
    "fetch_site",
    "generate_status_report",
    "render_analytics",
    "render_daily",
    "render_report",
    "site_summary",
]
