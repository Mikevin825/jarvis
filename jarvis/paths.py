"""Where JARVIS keeps durable state.

Everything that must survive a restart lives under `state/`, which is
git-ignored. Tier 4 (memory), Tier 5 (schedule, notices) and Tier 6 (audit log)
all write here.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
NOTES_DIR = STATE_DIR / "notes"
MESSAGES_FILE = STATE_DIR / "messages.json"


def ensure_dirs() -> None:
    """Create the state tree. Safe to call repeatedly."""
    for path in (STATE_DIR, NOTES_DIR):
        path.mkdir(parents=True, exist_ok=True)
