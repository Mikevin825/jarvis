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
# Below this many uploads a "cadence" is not a trend, it is noise — the same
# reasoning as MIN_UPLOADS_FOR_VIEW_JUDGEMENT below.
MIN_UPLOADS_FOR_CADENCE = 5
# A channel this young cannot be judged on views; flagging every new channel
# would cry wolf. Only call low views a problem once there is a real sample.
MIN_UPLOADS_FOR_VIEW_JUDGEMENT = 5


@dataclass
class StatusReport:
    """The measured state of the business's online presence.

    `sites` and `channels` hold every configured target. A business can run
    more than one brand, so these are lists; `website` and `channel` remain as
    read-only accessors for the first of each, which keeps older callers and
    tests working.
    """

    generated_at: datetime
    sites: list = field(default_factory=list)
    channels: list = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)

    @property
    def website(self):
        """The first site, or None. Backwards-compatible accessor."""
        return self.sites[0] if self.sites else None

    @property
    def channel(self):
        """The first channel, or None. Backwards-compatible accessor."""
        return self.channels[0] if self.channels else None

    @property
    def healthy(self) -> bool:
        return not self.concerns


def build_report(
    websites: tuple = (),
    channels: tuple = (),
    now: datetime | None = None,
) -> StatusReport:
    """Read every configured surface and compute what is wrong.

    `now` is injectable so the freshness arithmetic is testable.
    """
    moment = now or datetime.now(timezone.utc)
    report = StatusReport(generated_at=moment)

    for url in websites:
        label = url or "(no url)"
        try:
            site = fetch_site(url)
        except Exception as exc:  # noqa: BLE001 - one surface must not kill the report
            report.errors.append(f"{label}: {type(exc).__name__}: {exc}")
            report.concerns.append(
                f"The website {label} could not be checked: {exc}"
            )
            continue

        report.sites.append(site)
        if not site.reachable:
            report.concerns.append(
                f"{site.title or site.url} is not reachable: {site.error}"
            )
        elif site.broken_paths:
            broken = ", ".join(p.url for p in site.broken_paths)
            report.concerns.append(
                f"Broken pages on {site.title or site.url}: {broken}"
            )

    for channel_ref in channels:
        label = channel_ref or "(no channel)"
        try:
            channel = fetch_channel(channel_ref)
        except YouTubeError as exc:
            report.errors.append(f"{label}: {exc}")
            report.concerns.append(f"YouTube could not be checked ({label}): {exc}")
            continue
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"{label}: {type(exc).__name__}: {exc}")
            report.concerns.append(f"YouTube could not be checked ({label}): {exc}")
            continue

        report.channels.append(channel)
        if channel.videos:
            report.concerns.extend(_channel_concerns(channel, moment))

    return report


def _channel_concerns(channel: Channel, now: datetime) -> list[str]:
    """Flag the things a channel owner would want to know without asking."""
    concerns: list[str] = []
    videos = channel.videos
    if not videos:
        return concerns

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

    # -- websites ---------------------------------------------------------
    for site in report.sites:
        lines.append(f"Website: {site.url}")
        if site.reachable:
            lines.append("  Status: up (HTTP 200)")
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

    # -- channels ---------------------------------------------------------
    for ch in report.channels:
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
    for error in report.errors:
        lines.append(f"Error: {error}")

    return "\n".join(lines)


def generate_status_report(
    websites: tuple = (),
    channels: tuple = (),
    provider=None,
    now: datetime | None = None,
) -> str:
    """Build and render the report, with a short read from the model if available.

    The model is optional and only ever *adds* to the measured facts — the
    numbers stand on their own without it, so the report still works offline.
    """
    report = build_report(websites=websites, channels=channels, now=now)
    body = render_report(report)

    if provider is None:
        return body

    try:
        facts = body[:6000]
        targets = []
        if websites:
            targets.append(f"{len(websites)} website(s)")
        if channels:
            targets.append(f"{len(channels)} channel(s)")
        subject = " and ".join(targets) or "their online presence"
        prompt = (
            "You are JARVIS, the user's business advisor. Below is a measured "
            f"status report on {subject}. "
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
