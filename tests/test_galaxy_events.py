"""Tests for the galaxy event log.

The constellation reacts to agent events written by JARVIS. These tests cover
the writer: sequence numbers, capping, and recovery across a restart.
"""

from __future__ import annotations

import json
from pathlib import Path

from jarvis.galaxy_bridge import MAX_EVENTS, GalaxyBridge


def make_bridge(tmp_path: Path) -> GalaxyBridge:
    return GalaxyBridge(
        state_file=tmp_path / "galaxy-state.json",
        audio_file=tmp_path / "galaxy-audio.json",
        events_file=tmp_path / "galaxy-events.json",
    )


def test_dispatch_event_is_written(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    bridge.emit_dispatch("scout")

    events = bridge.read_events()
    assert len(events) == 1
    assert events[0]["type"] == "dispatch"
    assert events[0]["agent"] == "scout"
    assert events[0]["seq"] == 1


def test_sequence_numbers_increase(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    bridge.emit_dispatch("scout")
    bridge.emit_working("scout", True)
    bridge.emit_working("scout", False)

    events = bridge.read_events()
    assert [e["seq"] for e in events] == [1, 2, 3]


def test_working_event_carries_the_flag(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    bridge.emit_working("board", True)
    bridge.emit_working("board", False)

    events = bridge.read_events()
    assert events[0]["working"] is True
    assert events[1]["working"] is False
    assert events[0]["agent"] == "board"


def test_state_event_maps_the_jarvis_state(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    bridge.emit_state("recording")

    events = bridge.read_events()
    assert events[0]["type"] == "state"
    # "recording" is JARVIS's word; "listening" is the galaxy's.
    assert events[0]["state"] == "listening"


def test_add_agent_event_carries_the_spec(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    spec = {
        "id": "builder",
        "name": "Builder",
        "specialty": "Writes code",
        "color": "#7dd3fc",
        "orbit": {"radius": 2.1, "speed": 0.11, "phase": 1.0, "tiltX": 0.2, "tiltZ": 0.1},
    }
    bridge.emit_add_agent(spec)

    events = bridge.read_events()
    assert events[0]["type"] == "add-agent"
    assert events[0]["spec"]["id"] == "builder"


def test_events_are_capped(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    for i in range(MAX_EVENTS + 25):
        bridge.emit_dispatch(f"agent-{i}")

    events = bridge.read_events()
    assert len(events) == MAX_EVENTS
    # The newest survive; the oldest are dropped.
    assert events[-1]["agent"] == f"agent-{MAX_EVENTS + 24}"


def test_sequence_survives_a_restart(tmp_path: Path) -> None:
    first = make_bridge(tmp_path)
    first.emit_dispatch("scout")
    first.emit_dispatch("board")

    # A fresh bridge over the same files must not reuse sequence numbers, or the
    # galaxy would skip the new events as already-seen.
    second = make_bridge(tmp_path)
    second.emit_dispatch("mindmap")

    events = second.read_events()
    assert events[-1]["seq"] == 3


def test_idle_event_is_written(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    bridge.emit_idle()

    events = bridge.read_events()
    assert events[0]["type"] == "idle"


def test_a_corrupt_event_file_does_not_crash(tmp_path: Path) -> None:
    events_file = tmp_path / "galaxy-events.json"
    events_file.write_text("{ this is not json", encoding="utf-8")

    # Construction must survive a hand-mangled file rather than taking JARVIS
    # down on startup.
    bridge = GalaxyBridge(
        state_file=tmp_path / "galaxy-state.json",
        audio_file=tmp_path / "galaxy-audio.json",
        events_file=events_file,
    )
    assert bridge.read_events() == []

    bridge.emit_dispatch("scout")
    assert bridge.read_events()[0]["seq"] == 1


def test_a_failed_write_does_not_raise(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    # Point the events file at a directory, so the write fails with OSError.
    bad_dir = tmp_path / "a-directory"
    bad_dir.mkdir()
    bridge.events_file = bad_dir

    # The contract is that a broken disk must never crash JARVIS.
    bridge.emit_dispatch("scout")


def test_events_file_is_valid_json(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    bridge.emit_dispatch("scout")
    bridge.emit_working("board", True)

    raw = json.loads(bridge.events_file.read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    assert len(raw) == 2
