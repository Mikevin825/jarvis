"""Reminders with desktop notifications.

Set reminders that trigger desktop notifications at a specified time.
Uses notify-send for Linux desktop notifications.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from .base import Tool, ToolError

from ..paths import STATE_DIR

REMINDERS_FILE = STATE_DIR / "reminders.json"
CHECK_INTERVAL = 10  # seconds between reminder checks

_lock = threading.Lock()
_scheduler_thread = None
_scheduler_running = False


def _load_reminders() -> list[dict]:
    """Load reminders from disk."""
    try:
        raw = json.loads(REMINDERS_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_reminders(reminders: list[dict]) -> None:
    """Save reminders to disk."""
    REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    REMINDERS_FILE.write_text(json.dumps(reminders, indent=2), encoding="utf-8")


def _send_notification(title: str, body: str) -> None:
    """Send a desktop notification using notify-send."""
    try:
        subprocess.run(
            ["notify-send", "-u", "normal", "-t", "10000", title, body],
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # Notification failed — don't crash


def _scheduler_loop() -> None:
    """Background thread that checks for due reminders."""
    global _scheduler_running
    while _scheduler_running:
        now = datetime.now().astimezone()
        with _lock:
            reminders = _load_reminders()
            due = [r for r in reminders if datetime.fromisoformat(r["time"]) <= now]
            if due:
                # Remove due reminders
                remaining = [r for r in reminders if datetime.fromisoformat(r["time"]) > now]
                _save_reminders(remaining)
        for reminder in due:
            _send_notification(
                "JARVIS Reminder",
                reminder["message"],
            )
        time.sleep(CHECK_INTERVAL)


def _ensure_scheduler() -> None:
    """Start the background scheduler if not already running."""
    global _scheduler_thread, _scheduler_running
    if _scheduler_thread is None or not _scheduler_thread.is_alive():
        _scheduler_running = True
        _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
        _scheduler_thread.start()


def set_reminder(message: str, minutes: float) -> str:
    """Set a reminder that will trigger after the specified minutes.

    Args:
        message: The reminder message to show.
        minutes: How many minutes from now to trigger the reminder.
    """
    if not message or not message.strip():
        raise ToolError("No reminder message was given.")
    if minutes <= 0:
        raise ToolError("Reminder time must be in the future.")

    trigger_time = datetime.now().astimezone() + timedelta(minutes=minutes)

    reminder = {
        "id": f"reminder-{int(time.time() * 1000)}",
        "message": message.strip(),
        "time": trigger_time.isoformat(),
        "created_at": datetime.now().astimezone().isoformat(),
    }

    with _lock:
        reminders = _load_reminders()
        reminders.append(reminder)
        _save_reminders(reminders)

    _ensure_scheduler()

    time_str = trigger_time.strftime("%H:%M")
    return f"Reminder set for {time_str}: {message.strip()}"


def list_reminders() -> str:
    """List all active reminders."""
    with _lock:
        reminders = _load_reminders()

    if not reminders:
        return "No active reminders."

    now = datetime.now().astimezone()
    lines = ["Active reminders:"]
    for r in reminders:
        trigger = datetime.fromisoformat(r["time"])
        remaining = trigger - now
        if remaining.total_seconds() > 0:
            mins = int(remaining.total_seconds() / 60)
            secs = int(remaining.total_seconds() % 60)
            if mins > 0:
                time_str = f"{mins}m {secs}s"
            else:
                time_str = f"{secs}s"
        else:
            time_str = "due now"
        lines.append(f"  - {r['message']} (in {time_str})")

    return "\n".join(lines)


def cancel_reminder(reminder_id: str) -> str:
    """Cancel a reminder by its ID."""
    with _lock:
        reminders = _load_reminders()
        remaining = [r for r in reminders if r["id"] != reminder_id]
        if len(remaining) == len(reminders):
            raise ToolError(f"No reminder found with id '{reminder_id}'.")
        _save_reminders(remaining)

    return f"Reminder cancelled."


def build() -> list[Tool]:
    return [
        Tool(
            name="set_reminder",
            description=(
                "Use this to set a reminder for the user. The reminder will "
                "trigger a desktop notification after the specified minutes. "
                "Call it when the user asks to be reminded about something."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "message": {
                        "type": "STRING",
                        "description": "The reminder message to show.",
                    },
                    "minutes": {
                        "type": "NUMBER",
                        "description": "How many minutes from now to trigger the reminder.",
                    },
                },
                "required": ["message", "minutes"],
            },
            func=set_reminder,
        ),
        Tool(
            name="list_reminders",
            description=(
                "Use this to list all active reminders. Call it when the user "
                "asks what reminders are set."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {},
                "required": [],
            },
            func=list_reminders,
        ),
        Tool(
            name="cancel_reminder",
            description=(
                "Use this to cancel a reminder. The user must provide the "
                "reminder ID from list_reminders."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "reminder_id": {
                        "type": "STRING",
                        "description": "The ID of the reminder to cancel.",
                    },
                },
                "required": ["reminder_id"],
            },
            func=cancel_reminder,
        ),
    ]
