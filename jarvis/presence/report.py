"""The status report — website and YouTube channel read as one picture.

Deliberately deterministic: every number in the report is computed here rather
than asked of the model, so a report is reproducible and can be asserted on in
tests. The model is used only for the closing read, when one is available.

The report is built to be *useful on a schedule* as well as on demand, so it
leads with what changed and what is wrong rather than restating the site.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .website import SiteInfo, fetch_site
from .youtube import Channel, YouTubeError, fetch_channel

# How stale a channel may be before it is worth flagging.
STALE_AFTER_DAYS = 45
# Below this, a cadence claim is noise rather than a signal.
MIN_UPLOADS_FOR_CADENCE = 3
# A channel this young cannot be judged on views; flagging every new channel
# would cry wolf. Only call low views a problem once there is a real sample.
MIN_UPLOADS_FOR_VIEW_JUDGEMENT = 5


@dataclass
class StatusReport:
    """The measured state of the business's online presence."""

    generated_at: datetime
    website: SiteInfo | None = None
    channel: Channel | None = None
    website_error: str = ""
    channel_error: str = ""
    concerns: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not self.concerns


def build_report(
    website_url: str = "",
    channel: str = "",
    now: datetime | None = None,
) -> StatusReport:
    """Read both surfaces and compute what is wrong.

    `now` is injectable so the freshness arithmetic is testable.
    """
    moment = now or datetime.now(timezone.utc)
    report = StatusReport(generated_at=moment)

    # -- website ----------------------------------------------------------
    if website_url:
        try:
            report.website = fetch_site(website_url)
            if not report.website.reachable:
                report.website_error = report.website.error
                report.concerns.append(
                    f"The website is not reachable: {report.website.error}"
                )
            elif report.website.broken_paths:
                broken = ", ".join(p.url for p in report.website.broken_paths)
                report.website_error = f"{len(report.website.broken_paths)} broken page(s)"
                report.concerns.append(f"Broken pages on the website: {broken}")
        except Exception as exc:  # noqa: BLE001 - a report must not crash on one surface
            report.website_error = f"{type(exc).__name__}: {exc}"
            report.concerns.append(f"The website could not be checked: {report.website_error}")

    # -- YouTube ----------------------------------------------------------
    if channel:
        try:
            report.channel = fetch_channel(channel)
        except YouTubeError as exc:
            report.channel_error = str(exc)
            report.concerns.append(f"YouTube could not be checked: {exc}")
        except Exception as exc:  # noqa: BLE001
            report.channel_error = f"{type(exc).__name__}: {exc}"
            report.concerns.append(f"YouTube could not be checked: {report.channel_error}")

    if report.channel is not None and report.channel.videos:
        report.concerns.extend(_channel_concerns(report.channel, moment))

    return report


def _channel_concerns(channel: Channel, now: datetime) -> list[str]:
    """Flag the things a channel owner would want to know without asking."""
    concerns: list[str] = []
    videos = channel.videos

    newest = videos[0].published
    age = (now - newest).days
    if age >= STALE_AFTER_DAYS:
        concerns.append(
            f"The channel has not posted in {age} days "
            f"(last upload {_format_date(newest)})."
        )

    if len(videos) >= MIN_UPLOADS_FOR_CADENCE:
        oldest = videos[-1].published
        span = (newest - oldest).days
        cadence = span / (len(videos) - 1)
        if cadence >= 21:
            concerns.append(
                f"Upload cadence is one video every {cadence:.0f} days — "
                "worth checking against how often the channel intends to post."
            )

    total_views = sum(v.views for v in videos if v.views)
    if len(videos) >= MIN_UPLOADS_FOR_VIEW_JUDGEMENT and total_views:
        low = sum(1 for v in videos if 0 < v.views < 100)
        if low >= len(videos) // 2:
            concerns.append(
                f"{low} of the last {len(videos)} videos have under 100 views."
            )

    return concerns


# -- rendering --------------------------------------------------------------

def render_report(report: StatusReport) -> str:
    """Turn a report into prose worth reading in an inbox notice."""
    lines: list[str] = []
    lines.append("Business status report")
    lines.append(f"Generated: {report.generated_at.strftime('%d %b %Y, %H:%M')}")
    lines.append("")

    # -- headline: what is wrong, first ------------------------------------
    if report.healthy:
        lines.append("Everything checks out. The website is up and the channel is active.")
    else:
        lines.append(f"{len(report.concerns)} thing(s) worth your attention:")
        for concern in report.concerns:
            lines.append(f"  ! {concern}")
    lines.append("")

    # -- website ----------------------------------------------------------
    if report.website is not None:
        site = report.website
        lines.append(f"Website: {site.url}")
        if site.reachable:
            lines.append(f"  Status: up (HTTP 200)")
            lines.append(f"  Title: {site.title}")
            if site.broken_paths:
                lines.append(f"  Broken pages: {len(site.broken_paths)}")
                for broken in site.broken_paths:
                    lines.append(f"    - {broken.url} (HTTP {broken.status})")
            else:
                lines.append("  Broken pages: none")
        else:
            lines.append(f"  Status: DOWN — {site.error}")
        lines.append("")

    # -- YouTube ----------------------------------------------------------
    if report.channel is not None:
        ch = report.channel
        lines.append(f"YouTube: {ch.name}")
        lines.append(f"  Channel: {ch.url}")
        if ch.joined:
            lines.append(f"  Joined: {ch.joined.strftime('%B %Y')}")
        if not ch.videos:
            lines.append("  No videos in the feed.")
        else:
            newest = ch.videos[0].published
            age = (report.generated_at - newest).days
            lines.append(f"  Latest upload: {_format_date(newest)} ({age} days ago)")
            if len(ch.videos) >= MIN_UPLOADS_FOR_CADENCE:
                span = (newest - ch.videos[-1].published).days
                cadence = span / (len(ch.videos) - 1)
                lines.append(
                    f"  Cadence: one video every {cadence:.0f} days "
                    f"(across {len(ch.videos)} uploads)"
                )
            total = sum(v.views for v in ch.videos if v.views)
            if total:
                lines.append(f"  Views on the last {len(ch.videos)} videos: {total:,}")
            lines.append("")
            lines.append("  Recent uploads:")
            for video in ch.videos[:5]:
                lines.append(
                    f"    - {_format_date(video.published)} · {video.title} "
                    f"({video.views:,} views)"
                )
        lines.append("")

    # -- errors that produced no data --------------------------------------
    if report.website_error and report.website is None:
        lines.append(f"Website error: {report.website_error}")
    if report.channel_error and report.channel is None:
        lines.append(f"YouTube error: {report.channel_error}")

    return "\n".join(lines)


def generate_status_report(
    website_url: str = "",
    channel: str = "",
    provider=None,
) -> str:
    """Build and render the report, with a short read from the model if available.

    The model is optional and only ever *adds* to the measured facts — the
    numbers stand on their own without it, so the report still works offline.
    """
    report = build_report(website_url=website_url, channel=channel)
    body = render_report(report)

    if provider is None:
        return body

    try:
        facts = body[:6000]
        prompt = (
            "You are JARVIS, the user's business advisor. Below is a measured "
            "status report on their business website and YouTube channel. "
            "Write three to five sentences that read like a partner giving a "
            "status call: lead with what is wrong or at risk, then what is "
            "healthy, and end with the single most useful next step. Do not "
            "restate the raw numbers or repeat the headings.\n\n"
            f"REPORT:\n{facts}"
        )
        from ..providers import Message

        read = ""
        for event in provider.stream(prompt, [Message(role="user", content=prompt)]):
            from ..providers import TextDelta

            if isinstance(event, TextDelta):
                read += event.text

        read = read.strip()
        if read:
            return f"{body}\n\nJARVIS's read:\n{read}"
    except Exception:  # noqa: BLE001 - commentary is a bonus, never a blocker
        pass

    return body


def _format_date(moment: datetime | None) -> str:
    if not moment:
        return "unknown"
    return moment.strftime("%d %b %Y")
