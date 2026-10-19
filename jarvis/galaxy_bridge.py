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
GALAXY_EVENTS_FILE = STATE_DIR / "galaxy-events.json"

# How many events to keep. The galaxy reads the whole file each poll and skips
# anything it has already seen by sequence number, so this only needs to be
# long enough to survive a poll interval or two — 200 is generous.
MAX_EVENTS = 200

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
        events_file: Path = GALAXY_EVENTS_FILE,
    ) -> None:
        self.state_file = state_file
        self.audio_file = audio_file
        self.events_file = events_file
        self._last_state = ""
        self._last_write = 0.0
        self._write_interval = 0.5  # seconds
        self._event_seq = 0
        self._events: list[dict] = []
        self._load_events()

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

    # -- agent events -------------------------------------------------------
    #
    # The constellation reacts to what the sub-agents are actually doing. The
    # galaxy polls this file and applies anything with a sequence number it has
    # not seen. Events are capped, so the file cannot grow without bound.

    def _load_events(self) -> None:
        """Recover the event log so sequence numbers survive a restart."""
        try:
            raw = json.loads(self.events_file.read_text(encoding="utf-8"))
            events = raw if isinstance(raw, list) else raw.get("events", [])
            self._events = [e for e in events if isinstance(e, dict)]
            if self._events:
                self._event_seq = max(int(e.get("seq", 0)) for e in self._events)
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            self._events = []
            self._event_seq = 0

    def _emit(self, event_type: str, **fields) -> dict:
        """Append one event and write the log."""
        self._event_seq += 1
        event = {
            "seq": self._event_seq,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "type": event_type,
            **fields,
        }
        self._events.append(event)
        if len(self._events) > MAX_EVENTS:
            self._events = self._events[-MAX_EVENTS:]
        self._write_events()
        return event

    def _write_events(self) -> None:
        try:
            self.events_file.parent.mkdir(parents=True, exist_ok=True)
            self.events_file.write_text(
                json.dumps(self._events),
                encoding="utf-8",
            )
        except OSError:
            pass  # A failed write must not crash JARVIS

    def emit_state(self, jarvis_state: str) -> dict:
        """Announce a state change to the constellation."""
        return self._emit("state", state=map_state(jarvis_state))

    def emit_dispatch(self, agent_id: str) -> dict:
        """An agent was handed a task: fire its beam."""
        return self._emit("dispatch", agent=agent_id)

    def emit_working(self, agent_id: str, working: bool = True) -> dict:
        """An agent started or finished work: pulse it, dock it, or release it."""
        return self._emit("working", agent=agent_id, working=working)

    def emit_idle(self) -> dict:
        """Everything back to rest."""
        return self._emit("idle")

    def emit_add_agent(self, spec: dict) -> dict:
        """A new agent joined the constellation at runtime."""
        return self._emit("add-agent", spec=spec)

    def read_events(self) -> list[dict]:
        """Read the event log from disk."""
        try:
            raw = json.loads(self.events_file.read_text(encoding="utf-8"))
            return raw if isinstance(raw, list) else raw.get("events", [])
        except (OSError, json.JSONDecodeError):
            return []

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
