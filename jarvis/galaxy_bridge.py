"""The galaxy bridge — connects JARVIS to the galaxy.

JARVIS writes its current state and audio levels to JSON files. The galaxy
polls these files and updates the scene. No server, no WebSocket, no new
dependencies — just files on disk.

The bridge watches for state changes from the voice loop and brain, and writes
them to state/galaxy-state.json. It also taps the audio output and writes
levels to state/galaxy-audio.json.

The galaxy polls these files every 500ms and calls setState() and setLevels().
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from .paths import STATE_DIR

GALAXY_STATE_FILE = STATE_DIR / "galaxy-state.json"
GALAXY_AUDIO_FILE = STATE_DIR / "galaxy-audio.json"

# Map JARVIS internal states to galaxy states
STATE_MAP = {
    "idle": "idle",
    "arming": "arming",
    "recording": "listening",
    "transcribing": "thinking",
    "thinking": "thinking",
    "speaking": "speaking",
    "error": "error",
    "tooshort": "idle",
    "heardnothing": "idle",
    "interrupted": "idle",
}


def map_state(jarvis_state: str) -> str:
    """Map a JARVIS internal state to a galaxy state."""
    return STATE_MAP.get(jarvis_state, "idle")


class GalaxyBridge:
    """Watches JARVIS state changes and writes them to disk.

    The galaxy polls these files and updates the scene. This is the simplest
    possible connection — no server, no WebSocket, no new dependencies.
    """

    def __init__(
        self,
        state_file: Path = GALAXY_STATE_FILE,
        audio_file: Path = GALAXY_AUDIO_FILE,
    ) -> None:
        self.state_file = state_file
        self.audio_file = audio_file
        self._last_state = ""
        self._last_write = 0.0
        self._write_interval = 0.5  # seconds

    def set_state(self, jarvis_state: str) -> None:
        """Write the current state to disk.

        Called by the voice loop or brain when the state changes. Writes are
        throttled to avoid hammering the disk.
        """
        galaxy_state = map_state(jarvis_state)
        now = time.time()

        # Throttle writes — no need to write more than once per interval
        if galaxy_state == self._last_state and now - self._last_write < self._write_interval:
            return

        self._last_state = galaxy_state
        self._last_write = now

        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps({
                    "state": galaxy_state,
                    "jarvis_state": jarvis_state,
                    "timestamp": now,
                }),
                encoding="utf-8",
            )
        except OSError:
            pass  # A failed write must not crash JARVIS

    def set_audio_levels(self, voice: float, bass: float, treble: float) -> None:
        """Write the current audio levels to disk.

        Called by the voice loop or audio tap. Writes are throttled.
        """
        now = time.time()
        if now - self._last_write < self._write_interval:
            return

        self._last_write = now

        try:
            self.audio_file.parent.mkdir(parents=True, exist_ok=True)
            self.audio_file.write_text(
                json.dumps({
                    "voice": voice,
                    "bass": bass,
                    "treble": treble,
                    "timestamp": now,
                }),
                encoding="utf-8",
            )
        except OSError:
            pass

    def read_state(self) -> str:
        """Read the current galaxy state from disk."""
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
            return raw.get("state", "idle")
        except (OSError, json.JSONDecodeError):
            return "idle"

    def read_audio_levels(self) -> dict:
        """Read the current audio levels from disk."""
        try:
            raw = json.loads(self.audio_file.read_text(encoding="utf-8"))
            return {
                "voice": raw.get("voice", 0),
                "bass": raw.get("bass", 0),
                "treble": raw.get("treble", 0),
            }
        except (OSError, json.JSONDecodeError):
            return {"voice": 0, "bass": 0, "treble": 0}
