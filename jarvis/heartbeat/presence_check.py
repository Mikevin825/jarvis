"""The presence check — JARVIS watching the business's own surfaces.

The rule every heartbeat check obeys is that most runs produce nothing. This
one is no different, and it is the reason the check exists: a channel that
posts weekly and a site that stays up do not need announcing every day.

So the check remembers what it last saw and speaks up only when something
moved:

  * a website went down (or came back up)
  * a new video appeared on a channel
  * a page that used to work is now broken
  * a channel has gone quiet for longer than it usually does

Every target is tracked separately, so a second brand cannot hide behind the
first one staying healthy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..config import load_config, load_dotenv
from ..paths import STATE_DIR
from ..presence import build_report
from .checks import NORMAL, URGENT, CheckContext, CheckResult

STATE_FILE = STATE_DIR / "presence-check.json"

# How often a channel may go quiet before the check mentions it. Kept generous:
# a weekly channel should not be flagged after nine days.
QUIET_DAYS = 14


@dataclass
class SiteState:
    """What the check last observed about one website."""

    up: bool | None = None
    broken: list[str] = field(default_factory=list)
    seen: bool = False


@dataclass
class ChannelState:
    """What the check last observed about one channel."""

    last_video_id: str = ""
    quiet_reported: bool = False
    seen: bool = False


@dataclass
class PresenceState:
    """What the check last observed, per target, so it can spot a change."""

    sites: dict = field(default_factory=dict)
    channels: dict = field(default_factory=dict)
    last_seen_at: str = ""

    @classmethod
    def load(cls, path: Path = STATE_FILE) -> "PresenceState":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()

        # A state file from the single-target version has no "sites" map; treat
        # it as no history rather than crashing on the shape.
        if not isinstance(raw, dict) or "sites" not in raw:
            return cls()

        def _sites(raw_sites: dict | None) -> dict:
            out = {}
            for url, entry in (raw_sites or {}).items():
                entry = entry or {}
                out[url] = SiteState(
                    up=entry.get("up"),
                    broken=list(entry.get("broken") or []),
                    seen=bool(entry.get("seen", True)),
                )
            return out

        def _channels(raw_ch: dict | None) -> dict:
            out = {}
            for key, entry in (raw_ch or {}).items():
                entry = entry or {}
                out[key] = ChannelState(
                    last_video_id=str(entry.get("last_video_id", "")),
                    quiet_reported=bool(entry.get("quiet_reported", False)),
                    seen=bool(entry.get("seen", True)),
                )
            return out

        return cls(
            sites=_sites(raw.get("sites")),
            channels=_channels(raw.get("channels")),
            last_seen_at=str(raw.get("last_seen_at", "")),
        )

    def save(self, path: Path = STATE_FILE) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "sites": {
                            url: {"up": s.up, "broken": s.broken, "seen": s.seen}
                            for url, s in self.sites.items()
                        },
                        "channels": {
                            key: {
                                "last_video_id": c.last_video_id,
                                "quiet_reported": c.quiet_reported,
                                "seen": c.seen,
                            }
                            for key, c in self.channels.items()
                        },
                        "last_seen_at": self.last_seen_at,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass  # state is an optimisation; losing it must not break the check


class PresenceCheck:
    """Watches every configured website and YouTube channel.

    Quiet by default — surfaces only when something changes.
    """

    name = "presence"

    def __init__(self, interval_seconds: float, settings: dict) -> None:
        self.interval_seconds = interval_seconds
        self.settings = settings
        self.state = PresenceState.load()

    def run(self, ctx: CheckContext) -> CheckResult:
        """Read every surface. Never raises; never stacks on an in-flight run."""
        try:
            load_dotenv()
            cfg = load_config()
        except Exception as exc:  # noqa: BLE001 — a broken config must not kill the loop
            return CheckResult(summary=f"presence: could not load config: {exc}")

        websites = cfg.presence.all_websites
        channels = cfg.presence.all_channels
        if not websites and not channels:
            return CheckResult(summary="presence: nothing configured")

        try:
            report = build_report(websites=websites, channels=channels, now=ctx.now)
        except Exception as exc:  # noqa: BLE001
            return CheckResult(summary=f"presence error: {type(exc).__name__}: {exc}")

        # Keep score. This is what makes `--analytics` possible later: a report
        # is a snapshot, and only a series of them can show a trend.
        try:
            from ..presence.history import record

            record(sites=report.sites, channels=report.channels, taken_at=ctx.now)
        except Exception:  # noqa: BLE001 - history must never break the check
            pass

        changes = self._changes(report)
        self._remember(report, ctx)

        if not changes:
            bits = []
            if any(s.reachable for s in report.sites):
                bits.append(f"{len(report.sites)} site(s) up")
            if report.channels:
                bits.append(f"{len(report.channels)} channel(s) watched")
            return CheckResult(
                summary=f"presence: {', '.join(bits) or 'no change'}"
            )

        title, level = self._title(changes)
        return CheckResult(
            surfaced=True,
            title=title,
            body="\n".join(f"- {c}" for c in changes),
            level=level,
            summary=f"presence: {len(changes)} change(s)",
        )

    # -- deciding what changed ---------------------------------------------

    def _changes(self, report) -> list[str]:
        """Differences worth telling the user about, most serious first."""
        changes: list[str] = []

        for site in report.sites:
            name = site.title or site.url
            state = self.state.sites.setdefault(site.url, SiteState())
            was_up = state.up

            if was_up is True and not site.reachable:
                changes.append(f"{name} is DOWN: {site.error}")
            elif was_up is False and site.reachable:
                changes.append(f"{name} is back up.")
            elif was_up is None and not site.reachable:
                # First look at this site and it is already down — say it once.
                changes.append(f"{name} is not reachable: {site.error}")

            if site.reachable:
                broken = {p.url for p in site.broken_paths}
                new_broken = broken - set(state.broken)
                if new_broken:
                    changes.append(
                        f"New broken page(s) on {name}: "
                        + ", ".join(sorted(new_broken))
                    )

        for channel in report.channels:
            if not channel.videos:
                continue
            video = channel.videos[0]
            key = channel.channel_id or channel.url
            state = self.state.channels.setdefault(key, ChannelState())

            if state.last_video_id and video.video_id != state.last_video_id:
                age = (report.generated_at - video.published).days
                when = f"{age} day(s) ago" if age else "today"
                changes.append(
                    f"New video on {channel.name} ({when}): {video.title}"
                )
                state.quiet_reported = False  # it spoke; the silence is over
            elif not state.last_video_id:
                changes.append(
                    f"Channel watched: {channel.name} (latest: {video.title})"
                )

            age = (report.generated_at - video.published).days
            # Reported on the first run too: a channel silent for a month is the
            # most useful fact there is. The flag is what stops it repeating.
            if age >= QUIET_DAYS and not state.quiet_reported:
                changes.append(
                    f"{channel.name} has not posted in {age} days "
                    f"(usually more often than that)."
                )
                state.quiet_reported = True

        return changes

    def _remember(self, report, ctx: CheckContext) -> None:
        """Record what was seen, so the next run can compare."""
        for site in report.sites:
            state = self.state.sites.setdefault(site.url, SiteState())
            state.up = site.reachable
            state.seen = True
            if site.reachable:
                state.broken = [p.url for p in site.broken_paths]

        for channel in report.channels:
            if not channel.videos:
                continue
            key = channel.channel_id or channel.url
            state = self.state.channels.setdefault(key, ChannelState())
            state.last_video_id = channel.videos[0].video_id
            state.seen = True

        self.state.last_seen_at = ctx.now.isoformat()
        self.state.save()

    def _title(self, changes: list[str]) -> tuple[str, str]:
        """A headline that says what is wrong, not just that something moved."""
        if any("DOWN" in c or "not reachable" in c for c in changes):
            return "A website is down", URGENT
        if any("New video" in c for c in changes):
            return "New video on a channel", NORMAL
        if any("not posted" in c for c in changes):
            return "A channel has gone quiet", NORMAL
        if any("back up" in c or "broken page" in c for c in changes):
            return "A site changed state", NORMAL
        return "Something changed online", NORMAL
