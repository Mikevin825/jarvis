"""Tests for the presence heartbeat check.

The check's whole value is in *not* speaking, so the tests are mostly about
staying quiet: it must announce a baseline once, report a quiet channel once,
and then say nothing until something actually changes.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis.heartbeat.checks import CheckContext, build_checks
from jarvis.heartbeat.presence_check import (
    ChannelState,
    PresenceCheck,
    PresenceState,
    SiteState,
)
from jarvis.presence.youtube import Channel, Video

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
VIDEO_ID = "IhUyxSNCSF0"


def _video(days_ago: int, views: int = 10) -> Video:
    return Video(
        title="A video",
        video_id=VIDEO_ID,
        url="https://www.youtube.com/watch?v=" + VIDEO_ID,
        published=NOW - timedelta(days=days_ago),
        updated=NOW - timedelta(days=days_ago),
        description="",
        views=views,
    )


@pytest.fixture
def check(tmp_path, monkeypatch):
    """A PresenceCheck with a clean state that never touches the real file.

    `PresenceState.load`'s default path is bound at class-definition time, so
    monkeypatching the module constant would not help — the state is reset
    directly and saving is stubbed out instead.
    """
    monkeypatch.setattr("jarvis.heartbeat.presence_check.STATE_FILE", tmp_path / "state.json")
    instance = PresenceCheck(86400, {})
    instance.state = PresenceState()
    monkeypatch.setattr(PresenceState, "save", lambda self, path=None: None)
    return instance


def _context(now: datetime = NOW) -> CheckContext:
    return CheckContext(settings={}, now=now)


# -- construction ----------------------------------------------------------


class TestRegistration:
    def test_presence_is_a_known_check(self):
        checks = build_checks({"presence": {"enabled": True, "interval_seconds": 60}})
        assert [c.name for c in checks] == ["presence"]

    def test_disabled_presence_is_not_built(self):
        assert build_checks({"presence": {"enabled": False}}) == []

    def test_interval_comes_from_config(self):
        checks = build_checks({"presence": {"interval_seconds": 1234}})
        assert checks[0].interval_seconds == 1234.0


# -- state ------------------------------------------------------------------


class TestState:
    def test_round_trips(self, tmp_path):
        path = tmp_path / "s.json"
        state = PresenceState(
            sites={"https://a.test": SiteState(up=True)},
            channels={"UCa": ChannelState(last_video_id="abc", quiet_reported=True)},
        )
        state.save(path)

        loaded = PresenceState.load(path)
        assert loaded.sites["https://a.test"].up is True
        assert loaded.channels["UCa"].last_video_id == "abc"
        assert loaded.channels["UCa"].quiet_reported is True

    def test_missing_file_is_not_an_error(self, tmp_path):
        state = PresenceState.load(tmp_path / "nope.json")
        assert state.sites == {} and state.channels == {}

    def test_corrupt_file_is_not_an_error(self, tmp_path):
        path = tmp_path / "s.json"
        path.write_text("{not json", encoding="utf-8")
        assert PresenceState.load(path).sites == {}

    def test_single_target_state_file_is_treated_as_no_history(self, tmp_path):
        """An older `presence-check.json` must not crash the new loader."""
        path = tmp_path / "s.json"
        path.write_text(
            json.dumps({"last_video_id": "abc", "site_up": True}), encoding="utf-8"
        )
        state = PresenceState.load(path)
        assert state.sites == {} and state.channels == {}


# -- the quiet-reporting rule ----------------------------------------------


class TestQuietReporting:
    """A quiet channel must be announced once, not every day."""

    def _patch_report(self, monkeypatch, videos, *, sites=None, now=None):
        """Make build_report return fixed channels (and optionally sites).

        `now` is passed through: without it the report uses the real clock and
        a test whose NOW constant has drifted reports a different age than it
        intends to assert.
        """
        import jarvis.heartbeat.presence_check as mod

        channel = Channel(
            name="MINURO Studio", channel_id="UCx", url="u", joined=now or NOW,
            videos=videos,
        )
        report = mod.build_report(websites=(), channels=(), now=now or NOW)
        report.channels.append(channel)
        for site in (sites or []):
            report.sites.append(site)
        monkeypatch.setattr(mod, "build_report", lambda **kw: report)

    def test_first_run_establishes_a_baseline(self, check, monkeypatch):
        self._patch_report(monkeypatch, [_video(2)])
        result = check.run(_context())

        assert result.surfaced is True
        assert "Channel watched" in result.body

    def test_second_run_with_no_change_is_quiet(self, check, monkeypatch):
        self._patch_report(monkeypatch, [_video(2)])
        check.run(_context())
        second = check.run(_context())

        assert second.surfaced is False
        assert "channel" in second.summary

    def test_quiet_channel_reported_once_then_silent(self, check, monkeypatch):
        """The core discipline: one announcement, not a daily nag."""
        self._patch_report(monkeypatch, [_video(30)])
        first = check.run(_context())
        assert first.surfaced is True
        assert "not posted in 30 days" in first.body

        second = check.run(_context())
        assert second.surfaced is False, "a quiet channel must not be reported daily"

    def test_new_video_after_quiet_clears_the_flag(self, check, monkeypatch):
        """Posting again must reset the quiet state so it can fire next time."""
        self._patch_report(monkeypatch, [_video(30)])
        check.run(_context())          # reports quiet
        check.run(_context())          # silent

        # The channel posts again.
        new_video = Video(
            title="Fresh upload", video_id="NEW123",
            url="https://www.youtube.com/watch?v=NEW123",
            published=NOW, updated=NOW, description="", views=5,
        )
        self._patch_report(monkeypatch, [new_video])
        after = check.run(_context())

        assert after.surfaced is True
        assert "New video" in after.body
        assert check.state.channels["UCx"].quiet_reported is False


class TestMultipleTargets:
    """A second brand must not hide behind the first one staying healthy."""

    def _patch_two_channels(self, monkeypatch, *, quiet_id, fresh_id):
        """Two channels: `quiet_id` is silent for 30 days, `fresh_id` posted."""
        import jarvis.heartbeat.presence_check as mod

        quiet = Channel(
            name="Quiet Channel", channel_id=quiet_id, url="uq", joined=NOW,
            videos=[
                Video(
                    title="Old video", video_id="OLD1",
                    url="https://www.youtube.com/watch?v=OLD1",
                    published=NOW - timedelta(days=30),
                    updated=NOW - timedelta(days=30),
                    description="", views=5,
                )
            ],
        )
        fresh = Channel(
            name="Fresh Channel", channel_id=fresh_id, url="uf", joined=NOW,
            videos=[
                Video(
                    title="Brand new", video_id="NEW1",
                    url="https://www.youtube.com/watch?v=NEW1",
                    published=NOW, updated=NOW, description="", views=5,
                )
            ],
        )
        report = mod.build_report(websites=(), channels=(), now=NOW)
        report.channels.extend([quiet, fresh])
        monkeypatch.setattr(mod, "build_report", lambda **kw: report)

    def test_only_the_quiet_channel_is_named(self, check, monkeypatch):
        self._patch_two_channels(monkeypatch, quiet_id="UCquiet", fresh_id="UCfresh")
        result = check.run(_context())

        assert result.surfaced is True
        # The quiet channel is named as quiet...
        assert "Quiet Channel has not posted in 30 days" in result.body
        # ...and the healthy one is not reported as quiet, only as a baseline.
        assert "Fresh Channel has not posted" not in result.body

    def test_a_healthy_channel_alone_produces_no_notice(self, check, monkeypatch):
        self._patch_two_channels(monkeypatch, quiet_id="UCquiet", fresh_id="UCfresh")
        check.run(_context())

        # Now both are quiet-free and unchanged: nothing to say.
        self._patch_two_channels(monkeypatch, quiet_id="UCquiet", fresh_id="UCfresh")
        second = check.run(_context())
        assert second.surfaced is False

    def test_one_site_down_is_named_not_masked(self, check, monkeypatch):
        """Two sites, one down: the healthy one must not hide the broken one."""
        import jarvis.heartbeat.presence_check as mod
        from jarvis.presence.report import SiteInfo

        good = SiteInfo(
            url="https://good.test", reachable=True, title="Good", text="ok"
        )
        bad = SiteInfo(
            url="https://bad.test", reachable=False, title="Bad", text="",
            error="HTTP 503",
        )
        report = mod.build_report(websites=(), channels=())
        report.sites.extend([good, bad])
        report.concerns.append("Bad is not reachable: HTTP 503")
        monkeypatch.setattr(mod, "build_report", lambda **kw: report)

        result = check.run(_context())

        assert result.surfaced is True
        assert "Bad" in result.body
        assert "not reachable" in result.body
        assert result.level == "urgent"
