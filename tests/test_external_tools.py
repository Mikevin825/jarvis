"""Tests for closing apps by name.

The bug these cover: `close_app` matched only on window *title*, which changes
with whatever the app is showing. The Files window is called "Documents" or
"Home", never "Files", so "close Files" always failed.
"""

from __future__ import annotations

import subprocess

import pytest

from jarvis.tools.external import _matches_window, close_app


class TestWindowMatching:
    """The matcher must reach a window through its class, not just its title."""

    @pytest.mark.parametrize(
        "query,win_class,win_title,expected",
        [
            # The reported bug: title says "Documents", class says nautilus.
            ("files", "org.gnome.Nautilus", "Documents", True),
            ("Files", "org.gnome.Nautilus", "Home", True),
            ("file manager", "nemo.Nemo", "King", True),
            ("FILE MANAGER", "nemo.Nemo", "King", True),
            # Class matches even when the title is unrelated.
            ("terminal", "gnome-terminal-server.Gnome-terminal", "King Terminal", True),
            ("browser", "Navigator.zen", "WhatsApp — Zen Browser", True),
            ("music", "vlc.vlc", "Episode 4 - VLC media player", True),
            # A literal title still matches, as before.
            ("Hermes", "hermes.Hermes", "King Hermes", True),
            # And a wrong app must not match.
            ("terminal", "vlc.vlc", "Episode 4", False),
            ("files", "vlc.vlc", "Documents", False),
            ("browser", "org.gnome.Nautilus", "Documents", False),
        ],
    )
    def test_matches(self, query, win_class, win_title, expected):
        assert _matches_window(query, win_class, win_title) is expected

    def test_empty_query_matches_nothing(self):
        assert _matches_window("", "nautilus.Nautilus", "Documents") is False
        assert _matches_window("   ", "nautilus.Nautilus", "Documents") is False


class TestCloseApp:
    def _wmctrl(self, monkeypatch, stdout: str, returncode: int = 0):
        def fake_run(cmd, **kwargs):
            class R:
                pass

            r = R()
            r.stdout = stdout
            r.returncode = returncode
            r.stderr = ""
            return r

        monkeypatch.setattr(subprocess, "run", fake_run)

    def test_empty_title_is_refused(self):
        with pytest.raises(Exception) as exc:
            close_app("")
        assert "No window title" in str(exc.value)

    def test_no_match_says_so(self, monkeypatch):
        self._wmctrl(
            monkeypatch,
            "0x01  0  nautilus.Nautilus  Documents\n"
            "0x02  0  vlc.vlc  Episode 4\n",
        )
        result = close_app("spreadsheet")
        assert "No windows found" in result

    def test_matches_by_class_and_closes(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            class R:
                pass

            r = R()
            r.returncode = 0
            r.stderr = ""
            if cmd[:2] == ["wmctrl", "-lx"]:
                r.stdout = (
                    "0x01  0  nautilus.Nautilus  Documents\n"
                    "0x02  0  vlc.vlc  Episode 4\n"
                )
            else:
                calls.append(cmd)
                r.stdout = ""
            return r

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = close_app("files")

        assert "Closed 1 window(s)" in result
        # The window id must come from the class match, and be closed by id.
        assert calls == [["wmctrl", "-i", "-c", "0x01"]]

    def test_title_match_still_works(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            class R:
                pass

            r = R()
            r.returncode = 0
            r.stderr = ""
            if cmd[:2] == ["wmctrl", "-lx"]:
                r.stdout = "0x07  0  hermes.Hermes  King Hermes\n"
            else:
                r.stdout = ""
            return r

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert "Closed 1 window(s)" in close_app("Hermes")

    def test_multiple_matches_all_closed(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            class R:
                pass

            r = R()
            r.returncode = 0
            r.stderr = ""
            if cmd[:2] == ["wmctrl", "-lx"]:
                r.stdout = (
                    "0x01  0  nautilus.Nautilus  Documents\n"
                    "0x02  0  org.gnome.Nautilus  Home\n"
                )
            else:
                r.stdout = ""
            return r

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert "Closed 2 window(s)" in close_app("files")

    def test_malformed_lines_are_skipped(self, monkeypatch):
        """wmctrl can print a header or a truncated line; neither may crash it."""

        def fake_run(cmd, **kwargs):
            class R:
                pass

            r = R()
            r.returncode = 0
            r.stderr = ""
            if cmd[:2] == ["wmctrl", "-lx"]:
                r.stdout = "garbage\n\n0x01  0  nautilus.Nautilus  Documents\n"
            else:
                r.stdout = ""
            return r

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert "Closed 1 window(s)" in close_app("files")

    def test_wmctrl_missing_falls_back_to_xdotool(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            if cmd[0] == "wmctrl":
                raise FileNotFoundError("wmctrl")
            class R:
                pass

            r = R()
            r.returncode = 0
            r.stdout = ""
            r.stderr = ""
            return r

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert "Sent close command" in close_app("files")

    def test_both_missing_is_an_actionable_error(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError(cmd[0])

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(Exception) as exc:
            close_app("files")
        assert "Neither wmctrl nor xdotool" in str(exc.value)
