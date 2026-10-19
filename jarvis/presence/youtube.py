"""YouTube channel status, read from the public RSS feed.

No API key and no scraping of the channel page: every YouTube channel exposes
an Atom feed at

    https://www.youtube.com/feeds/videos.xml?channel_id=<UC...>

which carries the channel name, its join date, and the most recent videos with
title, description, publish date, and view count. That is enough for a status
report and needs no credentials.

Handles (`@minurostudio`) are not channel ids, so the handle is resolved to a
channel id first by reading the channel page and pulling `externalId` out of
the embedded JSON. The resolved id is cached on disk so the lookup happens
once per channel rather than on every report.
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ..paths import STATE_DIR

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Kept separate so the curl call and the httpx call send the same client string.
_BROWSER_UA = _HEADERS["User-Agent"]

_ATOM = "{http://www.w3.org/2005/Atom}"
_MEDIA = "{http://search.yahoo.com/mrss/}"
_YT = "{http://www.youtube.com/xml/schemas/2015}"

# The RSS feed carries roughly 15 entries; a channel that has posted more than
# this is still reported correctly, just with a shorter window of history.
MAX_VIDEOS = 15

CHANNEL_CACHE_FILE = STATE_DIR / "youtube-channels.json"


class YouTubeError(RuntimeError):
    """The channel could not be read. Carries a message worth showing."""


@dataclass
class Video:
    """One upload, as the feed describes it."""

    title: str
    video_id: str
    url: str
    published: datetime
    updated: datetime
    description: str
    views: int


@dataclass
class Channel:
    """A channel and its recent uploads."""

    name: str
    channel_id: str
    url: str
    joined: datetime | None
    videos: list[Video] = field(default_factory=list)

    @property
    def handle(self) -> str:
        return f"@{self.name.replace(' ', '')}"


# -- resolving a handle or URL to a channel id ------------------------------

def _load_cache() -> dict:
    try:
        return json.loads(CHANNEL_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CHANNEL_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CHANNEL_CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except OSError:
        pass  # a failed cache write is not worth failing the report over


def _channel_id_from_input(channel: str) -> str | None:
    """Extract a channel id if the caller already supplied one or a channel URL."""
    value = (channel or "").strip()
    if not value:
        return None

    match = re.search(r"channel/(UC[A-Za-z0-9_-]{22})", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", value):
        return value
    return None


def _resolve_via_curl(url: str) -> str:
    """Fetch a URL with curl and return the body.

    YouTube's consent wall blocks httpx: its TLS fingerprint is not a browser's,
    so the request is bounced to consent.youtube.com and the channel id is
    never present. curl presents a normal client fingerprint and gets the real
    page. Only this one lookup needs it — the RSS feed itself is fine over
    httpx, and the result is cached so it runs once per channel.
    """
    import shutil
    import subprocess

    if shutil.which("curl") is None:
        return ""

    try:
        result = subprocess.run(
            [
                "curl", "-sL", "--max-time", "25",
                "-A", _BROWSER_UA,
                "-H", "Accept-Language: en-US,en;q=0.9",
                url,
            ],
            capture_output=True,
            timeout=35,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""

    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", "replace")


def resolve_channel(channel: str) -> str:
    """Turn a handle, a URL, or a channel id into a channel id.

    A handle such as `@minurostudio` is looked up once and cached, so the
    channel page is only fetched when the cache has no entry for it.
    """
    value = (channel or "").strip()
    if not value:
        raise YouTubeError("No YouTube channel was given.")

    direct = _channel_id_from_input(value)
    if direct:
        return direct

    # Normalise `@handle`, `youtube.com/@handle` and bare `handle` alike.
    handle = value
    handle = re.sub(r"^https?://", "", handle).strip("/")
    handle = handle.rsplit("/@", 1)[-1].rsplit("/", 1)[-1]
    handle = handle.lstrip("@")
    if not handle:
        raise YouTubeError(f"Could not read a channel out of '{channel}'.")

    cache = _load_cache()
    if handle in cache:
        return cache[handle]

    # Pull the channel id out of the channel page's embedded JSON.
    url = f"https://www.youtube.com/@{handle}"

    page = _resolve_via_curl(url)
    if not page:
        # curl unavailable or blocked — try httpx before giving up.
        try:
            response = httpx.get(
                url, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True
            )
            page = response.text if response.status_code == 200 else ""
        except httpx.HTTPError:
            page = ""

    if not page:
        raise YouTubeError(
            f"Could not look up @{handle}. Paste the full channel URL "
            "(youtube.com/channel/UC…) instead."
        )

    match = re.search(r'"externalId":"(UC[A-Za-z0-9_-]{22})"', page)
    if not match:
        match = re.search(r'channel/(UC[A-Za-z0-9_-]{22})', page)
    if not match:
        raise YouTubeError(
            f"Could not find a channel id for @{handle}. "
            "Paste the full channel URL instead."
        )

    channel_id = match.group(1)
    cache[handle] = channel_id
    _save_cache(cache)
    return channel_id


# -- the feed ---------------------------------------------------------------

def fetch_channel(channel: str, max_videos: int = MAX_VIDEOS) -> Channel:
    """Read a channel and its recent uploads from its RSS feed."""
    channel_id = resolve_channel(channel)
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

    try:
        response = httpx.get(url, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise YouTubeError(f"Could not reach the YouTube feed: {exc}") from exc

    if response.status_code == 404:
        raise YouTubeError(
            f"No channel exists with id {channel_id}. "
            "Check the handle or paste the channel URL from your browser."
        )
    if response.status_code != 200:
        raise YouTubeError(
            f"YouTube returned {response.status_code} for the channel feed."
        )

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise YouTubeError(f"YouTube returned a feed that could not be read: {exc}") from exc

    def text(node, path: str) -> str:
        found = node.find(path)
        return (found.text or "").strip() if found is not None else ""

    name = text(root, f"{_ATOM}title") or f"@{channel_id}"
    joined_raw = text(root, f"{_ATOM}published")
    joined = _parse_date(joined_raw) if joined_raw else None

    videos: list[Video] = []
    for entry in root.findall(f"{_ATOM}entry"):
        group = entry.find(f"{_MEDIA}group")

        video_id = text(entry, f"{_YT}videoId")
        if not video_id:
            continue

        published_raw = text(entry, f"{_ATOM}published")
        updated_raw = text(entry, f"{_ATOM}updated")
        if not published_raw:
            continue

        # The feed repeats the title inside media:group; the entry title is the
        # canonical one, so only fall back when it is missing.
        title = text(entry, f"{_ATOM}title")
        if group is not None:
            title = title or text(group, f"{_MEDIA}title")
        description = ""
        if group is not None:
            description = text(group, f"{_MEDIA}description")

        # View counts live in media:community, nested inside media:group —
        # not a direct child of the entry.
        stats = None
        if group is not None:
            stats = group.find(f"{_MEDIA}community/{_MEDIA}statistics")

        videos.append(
            Video(
                title=title,
                video_id=video_id,
                url=f"https://www.youtube.com/watch?v={video_id}",
                published=_parse_date(published_raw),
                updated=_parse_date(updated_raw) or _parse_date(published_raw),
                description=description,
                views=int(stats.get("views", 0) or 0) if stats is not None else 0,
            )
        )
        if len(videos) >= max_videos:
            break

    return Channel(
        name=name,
        channel_id=channel_id,
        url=f"https://www.youtube.com/channel/{channel_id}",
        joined=joined,
        videos=videos,
    )


def _parse_date(raw: str) -> datetime | None:
    """Parse an ISO-8601 timestamp from the feed, tolerating a trailing Z."""
    if not raw:
        return None
    value = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


# -- the summary the model actually reads -----------------------------------

def channel_summary(channel: str, max_videos: int = MAX_VIDEOS) -> str:
    """A plain-text briefing on the channel, for the model to reason over."""
    ch = fetch_channel(channel, max_videos=max_videos)

    lines = [f"YouTube channel: {ch.name}", f"Channel: {ch.url}"]
    if ch.joined:
        lines.append(f"Channel created: {ch.joined.strftime('%B %Y')}")
    lines.append(f"Videos in the latest {len(ch.videos)} published: {len(ch.videos)}")
    lines.append("")

    if not ch.videos:
        lines.append("No videos found in the channel feed.")
        return "\n".join(lines)

    newest = ch.videos[0].published
    oldest = ch.videos[-1].published
    span_days = (newest - oldest).days if newest and oldest else 0

    lines.append(f"Most recent upload: {_format_date(newest)}")
    lines.append("")
    lines.append("Recent uploads:")
    for video in ch.videos[:max_videos]:
        date = _format_date(video.published)
        views = f"{video.views:,} views" if video.views else "view count not yet available"
        lines.append(f"- {date} · {video.title}")
        lines.append(f"    {views} · {video.url}")
        if video.description:
            # Descriptions run long; the model needs the shape, not the ad copy.
            summary = " ".join(video.description.split())
            lines.append(f"    {summary[:300]}")

    lines.append("")
    if span_days > 0 and len(ch.videos) > 1:
        cadence = span_days / (len(ch.videos) - 1)
        lines.append(
            f"Upload cadence: about one video every {cadence:.0f} days "
            f"over the last {span_days} days."
        )
    else:
        lines.append("Upload cadence: not enough uploads to measure yet.")

    return "\n".join(lines)


def _format_date(moment: datetime | None) -> str:
    if not moment:
        return "unknown date"
    return moment.strftime("%d %b %Y")
