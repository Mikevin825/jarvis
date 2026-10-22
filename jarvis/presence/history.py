"""Presence history — the record that makes analytics possible.

A status report is a snapshot: it says where things stand today and nothing
about where they were. That is fine for "is the site up" and useless for "are
views growing", which is the question a channel owner actually asks.

So every check appends a snapshot to a small SQLite database. Snapshots are
append-only and cheap — a daily check on two channels is a few thousand rows a
year — and storing per-video views (not just a channel total) is what makes
the interesting questions answerable later: which video grew, how fast, and
whether the channel is accelerating or stalling.

The schema is three tables off a `snapshots` parent:

    snapshots          one row per check, with the time it was taken
    site_snapshots     one row per website in that check
    channel_snapshots  one row per channel in that check
    video_snapshots    one row per video in that check — the views over time

Nothing here ever updates or deletes. History that can be rewritten is not
history.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..paths import STATE_DIR

DB_PATH = STATE_DIR / "presence-history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at   TEXT NOT NULL,
    targets    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS site_snapshots (
    snapshot_id      INTEGER NOT NULL REFERENCES snapshots(id),
    url              TEXT NOT NULL,
    name             TEXT,
    reachable        INTEGER,
    status           TEXT,
    broken_count     INTEGER DEFAULT 0,
    response_time_ms INTEGER,
    page_size_bytes  INTEGER,
    word_count       INTEGER,
    ssl_expires      TEXT,
    PRIMARY KEY (snapshot_id, url)
);

CREATE TABLE IF NOT EXISTS channel_snapshots (
    snapshot_id          INTEGER NOT NULL REFERENCES snapshots(id),
    channel_id           TEXT NOT NULL,
    name                 TEXT,
    video_count          INTEGER DEFAULT 0,
    total_views          INTEGER DEFAULT 0,
    latest_video_id      TEXT,
    latest_video_title   TEXT,
    latest_video_views   INTEGER,
    latest_video_published TEXT,
    PRIMARY KEY (snapshot_id, channel_id)
);

CREATE TABLE IF NOT EXISTS video_snapshots (
    snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id),
    channel_id   TEXT NOT NULL,
    video_id     TEXT NOT NULL,
    title        TEXT,
    views        INTEGER,
    published    TEXT,
    PRIMARY KEY (snapshot_id, channel_id, video_id)
);

CREATE INDEX IF NOT EXISTS idx_video_lookup
    ON video_snapshots (channel_id, video_id, snapshot_id);
CREATE INDEX IF NOT EXISTS idx_channel_time
    ON channel_snapshots (channel_id, snapshot_id);
CREATE INDEX IF NOT EXISTS idx_site_time
    ON site_snapshots (url, snapshot_id);
"""


def _connect() -> sqlite3.Connection:
    """Open the database, creating it and the schema if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


@contextmanager
def _db():
    """A connection that commits on success and always closes."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# -- writing ---------------------------------------------------------------


def record(
    sites: list | None = None,
    channels: list | None = None,
    taken_at: datetime | None = None,
) -> int:
    """Append one snapshot of the current state. Returns the snapshot id.

    `sites` are `SiteInfo` objects and `channels` are `Channel` objects, so
    the caller passes exactly what it already fetched — recording never
    triggers a second fetch.
    """
    moment = taken_at or datetime.now(timezone.utc)
    sites = sites or []
    channels = channels or []

    with _db() as conn:
        cursor = conn.execute(
            "INSERT INTO snapshots (taken_at, targets) VALUES (?, ?)",
            (moment.isoformat(), len(sites) + len(channels)),
        )
        snapshot_id = int(cursor.lastrowid)

        for site in sites:
            conn.execute(
                """
                INSERT INTO site_snapshots
                    (snapshot_id, url, name, reachable, status, broken_count,
                     response_time_ms, page_size_bytes, word_count, ssl_expires)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    site.url,
                    site.title or None,
                    1 if site.reachable else 0,
                    site.error or None,
                    len(site.broken_paths),
                    site.response_time_ms,
                    site.page_size_bytes,
                    site.word_count,
                    site.ssl_expires,
                ),
            )

        for channel in channels:
            videos = channel.videos
            total = sum(v.views for v in videos if v.views)
            latest = videos[0] if videos else None
            conn.execute(
                """
                INSERT INTO channel_snapshots
                    (snapshot_id, channel_id, name, video_count, total_views,
                     latest_video_id, latest_video_title, latest_video_views,
                     latest_video_published)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    channel.channel_id or channel.url,
                    channel.name,
                    len(videos),
                    total,
                    latest.video_id if latest else None,
                    latest.title if latest else None,
                    latest.views if latest else None,
                    latest.published.isoformat() if latest and latest.published else None,
                ),
            )
            for video in videos:
                conn.execute(
                    """
                    INSERT INTO video_snapshots
                        (snapshot_id, channel_id, video_id, title, views, published)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        channel.channel_id or channel.url,
                        video.video_id,
                        video.title,
                        video.views,
                        video.published.isoformat() if video.published else None,
                    ),
                )

    return snapshot_id


# -- reading ---------------------------------------------------------------


def snapshot_count() -> int:
    """How many snapshots exist — the length of the history."""
    with _db() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()
        return int(row["n"] or 0) if row else 0


def date_range() -> tuple[datetime | None, datetime | None]:
    """The oldest and newest snapshot times, or (None, None) if there is none."""
    with _db() as conn:
        row = conn.execute(
            "SELECT MIN(taken_at) AS first, MAX(taken_at) AS last FROM snapshots"
        ).fetchone()
    if not row or row["first"] is None:
        return None, None
    return _parse(row["first"]), _parse(row["last"])


def channel_video_views(
    channel_id: str, days: int | None = None
) -> dict[str, list[tuple[datetime, int]]]:
    """Views over time for every video on one channel.

    Returns `{video_id: [(when, views), ...]}` ordered oldest first, so a
    caller can plot growth without sorting. This is the core of the analytics:
    it is the only query that answers "is this video still getting views".
    """
    sql = """
        SELECT v.video_id, v.views, s.taken_at
        FROM video_snapshots v
        JOIN snapshots s ON s.id = v.snapshot_id
        WHERE v.channel_id = ?
    """
    params: list = [channel_id]
    if days is not None:
        sql += " AND s.taken_at >= ?"
        params.append(_days_ago(days).isoformat())
    sql += " ORDER BY s.taken_at ASC"

    with _db() as conn:
        rows = conn.execute(sql, params).fetchall()

    out: dict[str, list[tuple[datetime, int]]] = {}
    for row in rows:
        when = _parse(row["taken_at"])
        if when is None:
            continue
        out.setdefault(row["video_id"], []).append((when, int(row["views"] or 0)))
    return out


def channel_totals(channel_id: str, days: int | None = None) -> list[tuple[datetime, int, int]]:
    """Per-snapshot (time, video_count, total_views) for one channel."""
    sql = """
        SELECT s.taken_at, c.video_count, c.total_views
        FROM channel_snapshots c
        JOIN snapshots s ON s.id = c.snapshot_id
        WHERE c.channel_id = ?
    """
    params: list = [channel_id]
    if days is not None:
        sql += " AND s.taken_at >= ?"
        params.append(_days_ago(days).isoformat())
    sql += " ORDER BY s.taken_at ASC"

    with _db() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        when = _parse(r["taken_at"])
        if when is None:
            continue
        out.append((when, int(r["video_count"] or 0), int(r["total_views"] or 0)))
    return out


def site_uptime(url: str, days: int | None = None) -> tuple[float, int]:
    """(uptime_fraction, sample_count) for one website.

    The fraction is over the snapshots taken, not over elapsed time — a check
    that ran daily and saw the site up 29 of 30 days reports 0.967, which is
    the number a reader expects.
    """
    sql = """
        SELECT reachable, COUNT(*) AS n
        FROM site_snapshots
        WHERE url = ?
    """
    params: list = [url]
    if days is not None:
        sql += " AND snapshot_id IN (SELECT id FROM snapshots WHERE taken_at >= ?)"
        params.append(_days_ago(days).isoformat())
    sql += " GROUP BY reachable"

    with _db() as conn:
        rows = conn.execute(sql, params).fetchall()

    up = sum(int(r["n"]) for r in rows if r["reachable"] == 1)
    total = sum(int(r["n"]) for r in rows)
    if total == 0:
        return 0.0, 0
    return up / total, total


def site_metrics(
    url: str, days: int | None = None
) -> list[tuple[datetime, int | None, int | None, int | None]]:
    """Per-snapshot (time, response_ms, size_bytes, word_count) for one site.

    This is the website-analytics query: it is what makes "is the site getting
    slower" and "is the page growing" answerable from stored history.
    """
    sql = """
        SELECT s.taken_at, m.response_time_ms, m.page_size_bytes, m.word_count
        FROM site_snapshots m
        JOIN snapshots s ON s.id = m.snapshot_id
        WHERE m.url = ?
    """
    params: list = [url]
    if days is not None:
        sql += " AND s.taken_at >= ?"
        params.append(_days_ago(days).isoformat())
    sql += " ORDER BY s.taken_at ASC"

    with _db() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        when = _parse(r["taken_at"])
        if when is None:
            continue
        out.append((
            when,
            int(r["response_time_ms"]) if r["response_time_ms"] is not None else None,
            int(r["page_size_bytes"]) if r["page_size_bytes"] is not None else None,
            int(r["word_count"]) if r["word_count"] is not None else None,
        ))
    return out


def tracked_channels() -> list[str]:
    """Every channel id that has at least one snapshot."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT channel_id FROM channel_snapshots ORDER BY channel_id"
        ).fetchall()
    return [r["channel_id"] for r in rows]


def tracked_sites() -> list[str]:
    """Every site url that has at least one snapshot."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT url FROM site_snapshots ORDER BY url"
        ).fetchall()
    return [r["url"] for r in rows]


def video_titles(channel_id: str) -> dict[str, str]:
    """`{video_id: title}` from the most recent snapshot that has each video.

    Titles are needed because a video id is meaningless to a person reading a
    report, and the title is stored per snapshot so the latest one wins.
    """
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT v.video_id, v.title
            FROM video_snapshots v
            JOIN snapshots s ON s.id = v.snapshot_id
            WHERE v.channel_id = ?
            ORDER BY s.id DESC
            """,
            (channel_id,),
        ).fetchall()
    out: dict[str, str] = {}
    for row in rows:
        # First row per video_id is the newest, thanks to the ordering above.
        out.setdefault(row["video_id"], row["title"] or row["video_id"])
    return out


def channel_names() -> dict[str, str]:
    """`{channel_id: name}` from the most recent snapshot for each channel."""
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT c.channel_id, c.name
            FROM channel_snapshots c
            JOIN snapshots s ON s.id = c.snapshot_id
            ORDER BY s.id DESC
            """
        ).fetchall()
    out: dict[str, str] = {}
    for row in rows:
        out.setdefault(row["channel_id"], row["name"] or row["channel_id"])
    return out


def latest_snapshot() -> dict | None:
    """The most recent snapshot as a plain dict, or None if there is none."""
    with _db() as conn:
        row = conn.execute(
            "SELECT id, taken_at, targets FROM snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "taken_at": row["taken_at"], "targets": row["targets"]}


# -- helpers ---------------------------------------------------------------


def _parse(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _days_ago(days: int) -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=days)
