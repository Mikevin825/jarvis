"""Tests for the galaxy bridge.

The bridge connects JARVIS to the galaxy. JARVIS writes its current state and
audio levels to JSON files; the galaxy polls these files and updates the scene.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from jarvis.galaxy_bridge import GalaxyBridge, map_state


class TestMapState:
    def test_maps_recording_to_listening(self) -> None:
        assert map_state("recording") == "listening"

    def test_maps_transcribing_to_thinking(self) -> None:
        assert map_state("transcribing") == "thinking"

    def test_maps_thinking_to_thinking(self) -> None:
        assert map_state("thinking") == "thinking"

    def test_maps_speaking_to_speaking(self) -> None:
        assert map_state("speaking") == "speaking"

    def test_maps_error_to_error(self) -> None:
        assert map_state("error") == "error"

    def test_maps_idle_to_idle(self) -> None:
        assert map_state("idle") == "idle"

    def test_maps_unknown_to_idle(self) -> None:
        assert map_state("unknown") == "idle"

    def test_maps_tooshort_to_idle(self) -> None:
        assert map_state("tooshort") == "idle"

    def test_maps_heardnothing_to_idle(self) -> None:
        assert map_state("heardnothing") == "idle"

    def test_maps_interrupted_to_idle(self) -> None:
        assert map_state("interrupted") == "idle"


class TestGalaxyBridge:
    def test_set_state_writes_file(self, tmp_path: Path) -> None:
        state_file = tmp_path / "galaxy-state.json"
        bridge = GalaxyBridge(state_file=state_file)
        bridge.set_state("recording")
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        assert raw["state"] == "listening"
        assert raw["jarvis_state"] == "recording"

    def test_set_state_throttles_writes(self, tmp_path: Path) -> None:
        state_file = tmp_path / "galaxy-state.json"
        bridge = GalaxyBridge(state_file=state_file)
        bridge.set_state("recording")
        first_mtime = state_file.stat().st_mtime
        # Immediate second write should be throttled
        bridge.set_state("recording")
        assert state_file.stat().st_mtime == first_mtime

    def test_set_state_allows_different_state(self, tmp_path: Path) -> None:
        state_file = tmp_path / "galaxy-state.json"
        bridge = GalaxyBridge(state_file=state_file)
        bridge.set_state("recording")
        bridge.set_state("thinking")
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        assert raw["state"] == "thinking"

    def test_set_audio_levels_writes_file(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "galaxy-audio.json"
        bridge = GalaxyBridge(audio_file=audio_file)
        bridge.set_audio_levels(0.5, 0.3, 0.2)
        raw = json.loads(audio_file.read_text(encoding="utf-8"))
        assert raw["voice"] == 0.5
        assert raw["bass"] == 0.3
        assert raw["treble"] == 0.2

    def test_read_state_returns_idle_when_no_file(self, tmp_path: Path) -> None:
        state_file = tmp_path / "nonexistent.json"
        bridge = GalaxyBridge(state_file=state_file)
        assert bridge.read_state() == "idle"

    def test_read_state_returns_written_state(self, tmp_path: Path) -> None:
        state_file = tmp_path / "galaxy-state.json"
        bridge = GalaxyBridge(state_file=state_file)
        bridge.set_state("speaking")
        assert bridge.read_state() == "speaking"

    def test_read_audio_levels_returns_zero_when_no_file(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "nonexistent.json"
        bridge = GalaxyBridge(audio_file=audio_file)
        levels = bridge.read_audio_levels()
        assert levels == {"voice": 0, "bass": 0, "treble": 0}

    def test_read_audio_levels_returns_written_levels(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "galaxy-audio.json"
        bridge = GalaxyBridge(audio_file=audio_file)
        bridge.set_audio_levels(0.8, 0.6, 0.4)
        levels = bridge.read_audio_levels()
        assert levels["voice"] == 0.8
        assert levels["bass"] == 0.6
        assert levels["treble"] == 0.4

    def test_bridge_never_raises_on_write_failure(self, tmp_path: Path) -> None:
        # Point at a directory that can't be created
        state_file = tmp_path / "nonexistent-dir" / "galaxy-state.json"
        bridge = GalaxyBridge(state_file=state_file)
        # Should not raise
        bridge.set_state("recording")

    def test_bridge_never_raises_on_read_failure(self, tmp_path: Path) -> None:
        state_file = tmp_path / "galaxy-state.json"
        state_file.write_text("not json", encoding="utf-8")
        bridge = GalaxyBridge(state_file=state_file)
        # Should not raise, returns idle
        assert bridge.read_state() == "idle"
