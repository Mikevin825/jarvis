"""Where JARVIS keeps durable state.

Everything that must survive a restart lives under `state/`, which is
git-ignored. Tier 4 (memory), Tier 5 (schedule, notices) and Tier 6 (audit log)
all write here.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
REPORTS_DIR = ROOT / "reports"
NOTES_DIR = STATE_DIR / "notes"
MESSAGES_FILE = STATE_DIR / "messages.json"
MEMORY_FILE = STATE_DIR / "memory.txt"
# Tier 5 — the heartbeat
SCHEDULE_FILE = STATE_DIR / "schedule.json"
INBOX_FILE = STATE_DIR / "inbox.json"
AUDIT_FILE = STATE_DIR / "audit.log"
PAUSE_FILE = STATE_DIR / "PAUSED"
COST_FILE = STATE_DIR / "cost.json"


def ensure_dirs() -> None:
    """Create the state tree. Safe to call repeatedly."""
    for path in (STATE_DIR, NOTES_DIR):
        path.mkdir(parents=True, exist_ok=True)
