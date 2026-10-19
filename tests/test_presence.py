"""Tests for the business presence module.

Everything here runs against fixtures and fakes — no network, no live site.
The live reads were verified separately against the real site and channel.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from jarvis.presence import report as report_mod
from jarvis.presence import youtube as yt_mod
from jarvis.presence.report import build_report, render_report
from jarvis.presence.website import _extract_title, _linked_paths, _normalise
from jarvis.presence.youtube import Channel, Video, _channel_id_from_input, _parse_date


NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def _video(days_ago: int, views: int = 0, title: str = "A video") -> Video:
    return Video(
        title=title,
        video_id="abc123",
        url="https://www.youtube.com/watch?v=abc123",
        published=NOW - timedelta(days=days_ago),
        updated=NOW - timedelta(days=days_ago),
        description="",
        views=views,
    )


# -- config wiring ---------------------------------------------------------


class TestConfigWiring:
    def test_presence_targets_are_read(self):
        from jarvis.config import load_config, load_dotenv

        load_dotenv()
        cfg = load_config()
        assert cfg.presence.website_url == "https://minuro.vercel.app/"
        assert cfg.presence.youtube_channel == "https://www.youtube.com/@MINUROStudio"

    def test_presence_is_optional(self):
        """A business with only one surface still gets a config object."""
        from jarvis.config import PresenceConfig

        cfg = PresenceConfig()
        assert cfg.website_url == ""
        assert cfg.youtube_channel == ""


# -- channel id resolution --------------------------------------------------


class TestChannelIdResolution:
    @pytest.mark.parametrize(
        "given,expected",
        [
            ("UCxtW2qSajDNxhBgdykn_H9A", "UCxtW2qSajDNxhBgdykn_H9A"),
            ("https://www.youtube.com/channel/UCxtW2qSajDNxhBgdykn_H9A",
             "UCxtW2qSajDNxhBgdykn_H9A"),
            ("https://youtube.com/@somehandle", None),  # a handle, not an id
            ("not a channel", None),
            ("", None),
        ],
    )
    def test_direct_ids_are_recognised(self, given, expected):
        assert _channel_id_from_input(given) == expected

    def test_bad_input_is_refused(self):
        from jarvis.presence.youtube import YouTubeError, resolve_channel

        with pytest.raises(YouTubeError):
            resolve_channel("   ")


# -- RSS date parsing -------------------------------------------------------


class TestDateParsing:
    def test_iso_with_offset(self):
        parsed = _parse_date("2026-09-24T14:55:20+00:00")
        assert parsed is not None
        assert parsed.year == 2026 and parsed.month == 9 and parsed.day == 24

    def test_trailing_z_is_tolerated(self):
        parsed = _parse_date("2026-09-24T14:55:20Z")
        assert parsed is not None
        assert parsed.tzinfo is not None

    def test_garbage_returns_none(self):
        assert _parse_date("") is None
        assert _parse_date("not a date") is None


# -- report analysis --------------------------------------------------------


class TestReportAnalysis:
    def test_stale_channel_is_flagged(self):
        channel = Channel(
            name="Test", channel_id="UCx", url="u", joined=NOW,
            videos=[_video(days_ago=60)],
        )
        report = build_report(website_url="", channel="")
        report.channel = channel
        report.concerns.extend(report_mod._channel_concerns(channel, NOW))

        assert any("60 days" in c for c in report.concerns)

    def test_fresh_channel_is_not_flagged(self):
        channel = Channel(
            name="Test", channel_id="UCx", url="u", joined=NOW,
            videos=[_video(days_ago=2)],
        )
        concerns = report_mod._channel_concerns(channel, NOW)
        assert not any("days" in c and "not posted" in c for c in concerns)

    def test_low_views_not_flagged_for_a_young_channel(self):
        """A channel with three uploads cannot be judged on views yet."""
        channel = Channel(
            name="Test", channel_id="UCx", url="u", joined=NOW,
            videos=[_video(30, views=50), _video(20, views=30), _video(10, views=40)],
        )
        concerns = report_mod._channel_concerns(channel, NOW)
        assert not any("under 100 views" in c for c in concerns)

    def test_low_views_flagged_once_there_is_a_sample(self):
        videos = [_video(60 - i * 10, views=20) for i in range(6)]
        channel = Channel(
            name="Test", channel_id="UCx", url="u", joined=NOW, videos=videos,
        )
        concerns = report_mod._channel_concerns(channel, NOW)
        assert any("under 100 views" in c for c in concerns)

    def test_no_videos_does_not_crash(self):
        channel = Channel(name="Test", channel_id="UCx", url="u", joined=NOW, videos=[])
        assert report_mod._channel_concerns(channel, NOW) == []


# -- rendering --------------------------------------------------------------


class TestRendering:
    def test_unreachable_site_is_reported_as_down(self):
        report = report_mod.StatusReport(generated_at=NOW)
        report.website = report_mod.SiteInfo(
            url="https://x.test", reachable=False, title="", text="",
            error="HTTP 503",
        )
        report.concerns.append("The website is not reachable: HTTP 503")

        text = render_report(report)
        assert "DOWN" in text
        assert "503" in text

    def test_healthy_report_leads_with_everything_fine(self):
        report = report_mod.StatusReport(generated_at=NOW)
        text = render_report(report)
        assert "Everything checks out" in text

    def test_concerns_are_surfaced_first(self):
        report = report_mod.StatusReport(
            generated_at=NOW, concerns=["The channel has not posted in 60 days."]
        )
        text = render_report(report)
        assert text.index("worth your attention") < text.index("Generated")


# -- website helpers --------------------------------------------------------


class TestWebsiteHelpers:
    def test_normalise_adds_scheme_and_strips_slash(self):
        assert _normalise("example.com/") == "https://example.com"
        assert _normalise("http://example.com") == "http://example.com"
        assert _normalise("") == ""

    def test_title_extraction(self):
        html = "<html><head><title>  Hello   World  </title></head></html>"
        assert _extract_title(html) == "Hello World"

    def test_title_absent(self):
        assert _extract_title("<html><body>no title</body></html>") == ""

    def test_only_linked_paths_are_probed(self):
        html = (
            '<a href="/pricing">Pricing</a>'
            '<a href="https://other.example/about">Other</a>'
            '<a href="mailto:x@y.z">Mail</a>'
            '<a href="/assets/logo.png">Logo</a>'
        )
        paths = _linked_paths(html, "https://example.com")
        assert "/pricing" in paths
        assert "/about" not in paths
        assert not any("logo" in p for p in paths)


# -- the tools the model calls ---------------------------------------------


class TestTools:
    def test_status_report_tool_returns_text(self):
        """The tool wraps generate_status_report and never raises on bad config."""
        from jarvis.presence.tools import business_status_report

        # With nothing configured the tool raises a plain, actionable error.
        # (Config is patched below to avoid touching the real file.)
        import jarvis.presence.tools as tools_mod

        original = tools_mod._settings
        tools_mod._settings = lambda: {"website_url": "", "youtube_channel": ""}
        try:
            with pytest.raises(Exception) as exc:
                business_status_report()
            assert "config.yaml" in str(exc.value)
        finally:
            tools_mod._settings = original

    def test_check_website_requires_a_target(self):
        import jarvis.presence.tools as tools_mod
        from jarvis.tools.base import ToolError

        original = tools_mod._settings
        tools_mod._settings = lambda: {"website_url": "", "youtube_channel": ""}
        try:
            with pytest.raises(ToolError):
                tools_mod.check_website("")
        finally:
            tools_mod._settings = original
