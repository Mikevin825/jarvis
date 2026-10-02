"""Shared fixtures.

Every test runs against a temporary state directory, so tests never touch the
real memory, notes, outbox, or schedule. That matters more than usual here: the
whole point of the suite is to protect safety behaviour, and a test that mutates
real state would be its own hazard.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make the package importable when pytest is invoked from the repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def state_dir(tmp_path, monkeypatch):
    """Point every state path at a fresh temporary directory.

    The modules read their paths at import time, so they are monkeypatched
    rather than re-imported.
    """
    import jarvis.paths as paths

    for name in (
        "STATE_DIR",
        "NOTES_DIR",
        "MESSAGES_FILE",
        "MEMORY_FILE",
        "SCHEDULE_FILE",
        "INBOX_FILE",
        "AUDIT_FILE",
        "PAUSE_FILE",
        "COST_FILE",
    ):
        target = tmp_path / name.lower().replace("_file", ".json").replace("_dir", "")
        if name == "STATE_DIR":
            target = tmp_path
        elif name == "NOTES_DIR":
            target = tmp_path / "notes"
        elif name == "MEMORY_FILE":
            target = tmp_path / "memory.txt"
        elif name == "AUDIT_FILE":
            target = tmp_path / "audit.log"
        elif name == "PAUSE_FILE":
            target = tmp_path / "PAUSED"
        monkeypatch.setattr(paths, name, target, raising=False)

    # The tool modules imported these names directly, so patch them there too.
    import jarvis.tools.messages as messages_mod
    import jarvis.tools.notes as notes_mod

    monkeypatch.setattr(messages_mod, "MESSAGES_FILE", paths.MESSAGES_FILE, raising=False)
    monkeypatch.setattr(notes_mod, "NOTES_DIR", paths.NOTES_DIR, raising=False)

    paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def memory_store(state_dir):
    from jarvis.memory import MemoryStore

    return MemoryStore(state_dir / "memory.txt")


@pytest.fixture()
def registry(state_dir, memory_store):
    """A real registry with every tool, no gate attached."""
    from jarvis.tools import build_registry

    return build_registry(memory_store)
