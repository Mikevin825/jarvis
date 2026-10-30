"""Reminders with desktop notifications and voice output.

Set reminders that trigger desktop notifications and voice announcements at a 
specified time. Works both when JARVIS is running (via TTS) and when the 
background sentinel is active (via direct TTS calls).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .base import Tool, ToolError

from ..paths import STATE_DIR

REMINDERS_FILE = STATE_DIR / "reminders.json"
CHECK_INTERVAL = 10  # seconds between reminder checks

_lock = threading.Lock()
_scheduler_thread: Optional[threading.Thread] = None
_scheduler_running = False

# Module-level TTS configuration
_tts_config = None


@dataclass
class TTSConfig:
    """Configuration for TTS providers."""
    provider: str = "edge"
    api_key: str = ""
    voice: str = "en-GB-RyanNeural"
    model: str = ""
    rate_str: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"
    speed: float = 1.0
    timeout_seconds: float = 60.0
    voices_dir: Optional[str] = None
    length_scale: float = 1.0
    rate: int = 165
    normalize: bool = True


def _load_tts_config() -> TTSConfig:
    """Load TTS configuration from config.yaml."""
    config = {}
    try:
        import yaml
        config_path = Path.home() / ".jarvis" / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
    except Exception:
        pass
    
    tts_cfg = config.get("tts", {})
    providers = tts_cfg.get("providers", {})
    primary = providers.get(tts_cfg.get("provider", "edge"), {})
    
    return TTSConfig(
        provider=tts_cfg.get("provider", "edge"),
        api_key=os.environ.get(tts_cfg.get("api_key_env", ""), ""),
        voice=primary.get("voice", tts_cfg.get("voice", "en-GB-RyanNeural")),
        model=primary.get("model", tts_cfg.get("model", "")),
        rate_str=primary.get("rate_str", tts_cfg.get("rate_str", "+0%")),
        volume=primary.get("volume", tts_cfg.get("volume", "+0%")),
        pitch=primary.get("pitch", tts_cfg.get("pitch", "+0Hz")),
        speed=primary.get("speed", tts_cfg.get("speed", 1.0)),
        timeout_seconds=primary.get("timeout_seconds", tts_cfg.get("timeout_seconds", 60.0)),
        voices_dir=primary.get("voices_dir", tts_cfg.get("voices_dir")),
        length_scale=primary.get("length_scale", tts_cfg.get("length_scale", 1.0)),
        rate=primary.get("rate", tts_cfg.get("rate", 165)),
        normalize=primary.get("normalize", tts_cfg.get("normalize", True)),
    )


def _get_tts_config() -> TTSConfig:
    """Get TTS configuration lazily."""
    global _tts_config
    if _tts_config is None:
        _tts_config = _load_tts_config()
    return _tts_config


def _speak_text(text: str) -> bool:
    """Speak text using TTS if available."""
    tts_cfg = _get_tts_config()
    
    try:
        from jarvis.voice.tts import build_speaker_with_fallback, SpeechError
        speaker = build_speaker_with_fallback(tts_cfg)
        speaker.speak(text)
        return True
    except Exception as e:
        # Fallback to espeak command if TTS fails
        try:
            args = ["espeak-ng", "-v", "en-gb", text]
            result = subprocess.run(args, capture_output=True, timeout=10)
            return result.returncode == 0
        except Exception:
            return False


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


def _deliver_reminder(reminder: dict) -> None:
    """Deliver a reminder via both notification and voice."""
    message = reminder.get("message", "")
    title = reminder.get("title", "JARVIS Reminder")
    
    # Send desktop notification
    _send_notification(title, message)
    
    # Send voice reminder if enabled
    voice_enabled = os.environ.get("TTS_ENABLED", "true").lower() != "false"
    if voice_enabled:
        voice_message = f"{title}. {message}"
        _speak_text(voice_message)


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
            _deliver_reminder(reminder)
        time.sleep(CHECK_INTERVAL)


def _ensure_scheduler() -> None:
    """Start the background scheduler if not already running."""
    global _scheduler_thread, _scheduler_running
    if _scheduler_thread is None or not _scheduler_thread.is_alive():
        _scheduler_running = True
        _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
        _scheduler_thread.start()


def set_reminder(message: str, minutes: float, title: str = "JARVIS Reminder") -> str:
    """Set a reminder that will trigger after the specified minutes.

    Args:
        message: The reminder message to show.
        minutes: How many minutes from now to trigger the reminder.
        title: Optional title for the notification/announcement.
    """
    if not message or not message.strip():
        raise ToolError("No reminder message was given.")
    if minutes <= 0:
        raise ToolError("Reminder time must be in the future.")

    trigger_time = datetime.now().astimezone() + timedelta(minutes=minutes)

    reminder = {
        "id": f"reminder-{int(time.time() * 1000)}",
        "message": message.strip(),
        "title": title,
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

    return "Reminder cancelled."


def build() -> list[Tool]:
    return [
        Tool(
            name="set_reminder",
            description=(
                "Use this to set a reminder for the user. The reminder will "
                "trigger a desktop notification and voice announcement after the "
                "specified minutes. Call it when the user asks to be reminded about something."
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
                    "title": {
                        "type": "STRING",
                        "description": "Optional title for the notification/announcement.",
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


def start_scheduler():
    """Start the reminder scheduler. Call this when Jarvis starts.

    The scheduler runs as a daemon thread that checks for due reminders
    every 10 seconds. It continues running even if no reminders exist,
    so notifications will fire immediately when a reminder becomes due
    without waiting for another reminder to be set.
    """
    _ensure_scheduler()