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
from jarvis.presence.website import _linked_paths, _normalise
from jarvis.htmltext import extract_title
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

    def test_singular_fields_are_merged_into_the_plural_views(self):
        """Old config files keep working: the singular fields feed the lists."""
        from jarvis.config import PresenceConfig

        cfg = PresenceConfig(
            website_url="https://a.test",
            youtube_channel="https://www.youtube.com/@A",
            websites=("https://b.test",),
            youtube_channels=("https://www.youtube.com/@B",),
        )
        assert cfg.all_websites == ("https://a.test", "https://b.test")
        assert cfg.all_channels == (
            "https://www.youtube.com/@A",
            "https://www.youtube.com/@B",
        )

    def test_duplicates_are_removed(self):
        from jarvis.config import PresenceConfig

        cfg = PresenceConfig(
            website_url="https://a.test",
            websites=("https://a.test", "https://b.test"),
        )
        assert cfg.all_websites == ("https://a.test", "https://b.test")

    def test_empty_config_yields_no_targets(self):
        from jarvis.config import PresenceConfig

        cfg = PresenceConfig()
        assert cfg.all_websites == ()
        assert cfg.all_channels == ()


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
        report = build_report(websites=(), channels=())
        report.channels.append(channel)
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
        report.sites.append(
            report_mod.SiteInfo(
                url="https://x.test", reachable=False, title="", text="",
                error="HTTP 503",
            )
        )
        report.concerns.append("The website is not reachable: HTTP 503")

        text = render_report(report)
        assert "DOWN" in text
        assert "503" in text

    def test_healthy_report_leads_with_everything_fine(self):
        report = report_mod.StatusReport(generated_at=NOW)
        text = render_report(report)
        assert "Everything checks out" in text

    def test_multiple_sites_and_channels_are_all_rendered(self):
        report = report_mod.StatusReport(generated_at=NOW)
        report.sites.extend(
            [
                report_mod.SiteInfo(
                    url="https://a.test", reachable=True, title="Alpha", text="a"
                ),
                report_mod.SiteInfo(
                    url="https://b.test", reachable=True, title="Beta", text="b"
                ),
            ]
        )
        report.channels.extend(
            [
                Channel(
                    name="Channel A", channel_id="UCa", url="ua", joined=NOW,
                    videos=[_video(3, views=10)],
                ),
                Channel(
                    name="Channel B", channel_id="UCb", url="ub", joined=NOW,
                    videos=[_video(2, views=20)],
                ),
            ]
        )

        text = render_report(report)
        assert "Alpha" in text and "Beta" in text
        assert "Channel A" in text and "Channel B" in text
        assert text.count("Website:") == 2
        assert text.count("YouTube:") == 2

    def test_first_target_is_still_reachable_via_the_old_accessors(self):
        """`website`/`channel` keep working for older callers and tests."""
        report = report_mod.StatusReport(generated_at=NOW)
        report.sites.append(
            report_mod.SiteInfo(
                url="https://a.test", reachable=True, title="Alpha", text="a"
            )
        )
        report.channels.append(
            Channel(
                name="Channel A", channel_id="UCa", url="ua", joined=NOW,
                videos=[_video(3, views=10)],
            )
        )
        assert report.website is not None and report.website.title == "Alpha"
        assert report.channel is not None and report.channel.name == "Channel A"

    def test_concerns_are_surfaced_first(self):
        report = report_mod.StatusReport(
            generated_at=NOW,
            concerns=["The channel has not posted in 60 days."],
        )
        report.sites.append(
            report_mod.SiteInfo(
                url="https://x.test", reachable=True, title="X", text="hello"
            )
        )
        report.channels.append(
            Channel(
                name="Test", channel_id="UCx", url="u", joined=NOW,
                videos=[_video(60, views=10)],
            )
        )
        text = render_report(report)
        # Concerns must lead, ahead of the website and channel detail.
        assert text.index("worth your attention") < text.index("Website:")
        assert text.index("worth your attention") < text.index("YouTube:")
        assert "not posted in 60 days" in text


# -- website helpers --------------------------------------------------------


class TestWebsiteHelpers:
    def test_normalise_adds_scheme_and_strips_slash(self):
        assert _normalise("example.com/") == "https://example.com"
        assert _normalise("http://example.com") == "http://example.com"
        assert _normalise("") == ""

    def test_title_extraction(self):
        html = "<html><head><title>  Hello   World  </title></head></html>"
        assert extract_title(html) == "Hello World"

    def test_title_absent(self):
        assert extract_title("<html><body>no title</body></html>") == ""

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
        tools_mod._settings = lambda: ((), ())
        try:
            with pytest.raises(Exception) as exc:
                business_status_report()
            assert "config.yaml" in str(exc.value)
        finally:
            tools_mod._settings = original

    def test_the_first_configured_target_is_the_default_argument(self, monkeypatch):
        """Calling with no argument uses the first configured target.

        The fetchers are stubbed out so this tests the wiring — which target
        gets picked — rather than hitting the network.
        """
        import jarvis.presence.tools as tools_mod

        seen = {}

        def fake_site_summary(url):
            seen["site"] = url
            return "Alpha site"

        def fake_channel_summary(ref):
            seen["channel"] = ref
            return "Channel A summary"

        monkeypatch.setattr(tools_mod, "_settings", lambda: (("https://a.test",), ("@A",)))
        monkeypatch.setattr(tools_mod, "site_summary", fake_site_summary)
        monkeypatch.setattr(tools_mod, "channel_summary", fake_channel_summary)

        tools_mod.check_website()
        tools_mod.check_youtube_channel()

        assert seen["site"] == "https://a.test"
        assert seen["channel"] == "@A"

    def test_check_website_requires_a_target(self):
        import jarvis.presence.tools as tools_mod
        from jarvis.tools.base import ToolError

        original = tools_mod._settings
        tools_mod._settings = lambda: ((), ())
        try:
            with pytest.raises(ToolError):
                tools_mod.check_website("")
        finally:
            tools_mod._settings = original

    def test_check_youtube_channel_requires_a_target(self):
        import jarvis.presence.tools as tools_mod
        from jarvis.tools.base import ToolError

        original = tools_mod._settings
        tools_mod._settings = lambda: ((), ())
        try:
            with pytest.raises(ToolError):
                tools_mod.check_youtube_channel("")
        finally:
            tools_mod._settings = original
