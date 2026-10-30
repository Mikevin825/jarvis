#!/usr/bin/env python3
"""JARVIS Background Sentinel — independent system monitoring and reminders.

This script runs as a standalone background service that:
- Monitors system resources (CPU, memory, disk, temperature, battery)
- Processes scheduled reminders independently
- Generates alerts via desktop notifications AND voice

Usage:
    # One-shot check
    jarvis-sentinel --once
    
    # Run as daemon
    jarvis-sentinel
    
    # Status
    jarvis-sentinel --status
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Fallback when psutil is not available
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# Constants
STATE_DIR = Path.home() / ".jarvis" / "state"
SENTINEL_PID_FILE = STATE_DIR / "sentinel.pid"
INBOX_FILE = STATE_DIR / "inbox.json"
SCHEDULE_FILE = STATE_DIR / "schedule.json"
REMINDERS_FILE = STATE_DIR / "reminders.json"
NOTIFICATION_DEBOUNCER = STATE_DIR / "sentinel_debounce.json"


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


def ensure_dirs() -> None:
    """Ensure state directories exist."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load configuration from ~/.jarvis/config.yaml or defaults."""
    try:
        import yaml
        config_path = Path.home() / ".jarvis" / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    
    # Default configuration
    return {
        "heartbeat": {
            "enabled": True,
            "poll_seconds": 60,
            "voice_reminders_enabled": True,
            "checks": {
                "cpu": {"enabled": True, "warning_percent": 85.0, "critical_percent": 95.0, "interval_seconds": 60},
                "memory": {"enabled": True, "memory_warning_percent": 15.0, "memory_critical_percent": 7.0, "interval_seconds": 60},
                "disk": {"enabled": True, "disk_warning_percent": 85.0, "disk_critical_percent": 95.0, "interval_seconds": 300},
                "battery": {"enabled": True, "battery_warning_percent": 20.0, "battery_critical_percent": 10.0, "interval_seconds": 60},
            }
        }
    }


def load_tts_config() -> TTSConfig:
    """Load TTS configuration from config.yaml."""
    config = load_config()
    tts_cfg = config.get("tts", {})
    providers = tts_cfg.get("providers", {})
    primary = providers.get(tts_cfg.get("provider", "edge"), {})
    
    # Handle the case where config doesn't have nested structure
    if not primary and not providers:
        primary = {}
    
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


def send_notification(title: str, body: str, urgency: str = "normal") -> bool:
    """Send a desktop notification using notify-send."""
    try:
        args = ["notify-send", "-u", urgency, "-t", "15000", title, body]
        result = subprocess.run(args, capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return False


def speak_text(text: str, tts_cfg: TTSConfig) -> bool:
    """Speak text using TTS. Returns True if successful.
    
    Uses the existing JARVIS TTS infrastructure with fallbacks.
    """
    try:
        from jarvis.voice.tts import build_speaker_with_fallback, SpeechError
        
        # Build speaker with fallback chain (edge -> piper -> espeak)
        speaker = build_speaker_with_fallback(tts_cfg)
        speaker.speak(text)
        
        return True
    except Exception:
        # Fallback to espeak command if TTS fails
        try:
            args = ["espeak-ng", "-v", "en-gb", text]
            result = subprocess.run(args, capture_output=True, timeout=10)
            return result.returncode == 0
        except Exception:
            return False


def load_debouncer() -> dict:
    """Load the notification debouncer state."""
    if NOTIFICATION_DEBOUNCER.exists():
        try:
            return json.loads(NOTIFICATION_DEBOUNCER.read_text())
        except Exception:
            pass
    return {}


def save_debouncer(state: dict) -> None:
    """Save the notification debouncer state."""
    ensure_dirs()
    NOTIFICATION_DEBOUNCER.write_text(json.dumps(state, indent=2))


def check_cpu(config: dict) -> Optional[str]:
    """Check CPU usage and return alert message if needed."""
    if not HAS_PSUTIL:
        return None
    
    check_config = config.get("heartbeat", {}).get("checks", {}).get("cpu", {})
    if not check_config.get("enabled", True):
        return None
    
    warning = check_config.get("warning_percent", 85.0)
    critical = check_config.get("critical_percent", 95.0)
    
    try:
        cpu_percent = psutil.cpu_percent(interval=1.0)
        if cpu_percent >= critical:
            return f"CPU critical: {cpu_percent:.1f}% utilization exceeds {critical:.0f}% threshold."
        elif cpu_percent >= warning:
            return f"CPU warning: {cpu_percent:.1f}% utilization approaches {warning:.0f}% threshold."
    except Exception:
        pass
    
    return None


def check_memory(config: dict) -> Optional[str]:
    """Check memory usage and return alert message if needed."""
    if not HAS_PSUTIL:
        return None
    
    check_config = config.get("heartbeat", {}).get("checks", {}).get("memory", {})
    if not check_config.get("enabled", True):
        return None
    
    mem_warn = check_config.get("memory_warning_percent", 15.0)
    mem_crit = check_config.get("memory_critical_percent", 7.0)
    
    try:
        mem = psutil.virtual_memory()
        mem_available_pct = mem.available / mem.total * 100
        
        if mem_available_pct <= mem_crit:
            return f"Memory critical: only {mem_available_pct:.1f}% available ({mem.percent:.0f}% used)."
        elif mem_available_pct <= mem_warn:
            return f"Memory warning: {mem_available_pct:.1f}% available ({mem.percent:.0f}% used)."
    except Exception:
        pass
    
    return None


def check_disk(config: dict) -> Optional[str]:
    """Check disk usage and return alert message if needed."""
    if not HAS_PSUTIL:
        return None
    
    check_config = config.get("heartbeat", {}).get("checks", {}).get("disk", {})
    if not check_config.get("enabled", True):
        return None
    
    warn = check_config.get("disk_warning_percent", 85.0)
    crit = check_config.get("disk_critical_percent", 95.0)
    
    try:
        for path in ['/', '/home']:
            usage = psutil.disk_usage(path)
            pct = usage.percent
            if pct >= crit:
                return f"Disk critical: {path} at {pct:.0f}% ({usage.free / (1024**3):.1f}GB free)."
            elif pct >= warn:
                return f"Disk warning: {path} at {pct:.0f}% ({usage.free / (1024**3):.1f}GB free)."
    except Exception:
        pass
    
    return None


def check_battery(config: dict) -> Optional[str]:
    """Check battery level and return alert message if needed."""
    if not HAS_PSUTIL:
        return None
    
    check_config = config.get("heartbeat", {}).get("checks", {}).get("battery", {})
    if not check_config.get("enabled", True):
        return None
    
    warn_pct = check_config.get("battery_warning_percent", 20.0)
    crit_pct = check_config.get("battery_critical_percent", 10.0)
    
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            return None
        
        if not battery.power_plugged:
            if battery.percent <= crit_pct:
                return f"Battery critical: {battery.percent}% remaining."
            elif battery.percent <= warn_pct:
                return f"Battery low: {battery.percent}% remaining."
    except Exception:
        pass
    
    return None


def check_reminders() -> list[dict]:
    """Check for due reminders and return them."""
    if not REMINDERS_FILE.exists():
        return []
    
    try:
        reminders = json.loads(REMINDERS_FILE.read_text())
    except Exception:
        return []
    
    now = datetime.now().astimezone()
    due = []
    
    for reminder in reminders:
        try:
            when = datetime.fromisoformat(reminder.get("time", ""))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when <= now:
                due.append(reminder)
        except Exception:
            continue
    
    if due:
        # Remove due reminders
        remaining = [r for r in reminders if datetime.fromisoformat(r.get("time", "")) > now]
        REMINDERS_FILE.write_text(json.dumps(remaining, indent=2))
    
    return due


def deduplicate_alert(key: str, message: str, cooldown_minutes: int = 30) -> bool:
    """Check if this alert should be sent (not recently sent)."""
    state = load_debouncer()
    now = datetime.now(timezone.utc)
    
    last_alert = state.get(key, {})
    last_time = last_alert.get("time")
    
    if last_time:
        try:
            last_dt = datetime.fromisoformat(last_time)
            if now - last_dt < timedelta(minutes=cooldown_minutes):
                return False
        except Exception:
            pass
    
    state[key] = {"time": now.isoformat(), "message": message}
    save_debouncer(state)
    return True


def run_checks(config: dict) -> list[tuple[str, str, str]]:
    """Run all configured checks and return list of (title, message, level) tuples."""
    alerts = []
    
    # CPU check
    alert = check_cpu(config)
    if alert and deduplicate_alert("cpu", alert):
        alerts.append(("System Health - CPU", alert, "normal"))
    
    # Memory check
    alert = check_memory(config)
    if alert and deduplicate_alert("memory", alert):
        alerts.append(("System Health - Memory", alert, "normal"))
    
    # Disk check
    alert = check_disk(config)
    if alert and deduplicate_alert("disk", alert):
        alerts.append(("System Health - Disk", alert, "normal"))
    
    # Battery check
    alert = check_battery(config)
    if alert and deduplicate_alert("battery", alert):
        alerts.append(("System Health - Battery", alert, "normal"))
    
    return alerts


def send_reminder(reminder: dict, tts_cfg: TTSConfig) -> None:
    """Send a reminder as both notification AND voice."""
    message = reminder.get("message", "")
    title = reminder.get("title", "JARVIS Reminder")
    reminder_id = reminder.get("id", "")
    
    if not deduplicate_alert(f"reminder-{reminder_id}", message, cooldown_minutes=1):
        return
    
    # Send desktop notification
    send_notification(title, message, "normal")
    
    # Send voice reminder if enabled
    voice_enabled = os.environ.get("TTS_ENABLED", "true").lower() != "false"
    if voice_enabled:
        voice_message = f"{title}. {message}"
        speak_text(voice_message, tts_cfg)


def send_reminders(reminders: list[dict], tts_cfg: TTSConfig) -> None:
    """Send reminder notifications."""
    for reminder in reminders:
        send_reminder(reminder, tts_cfg)


def run_once() -> int:
    """Run a single check cycle. Returns exit code."""
    config = load_config()
    tts_cfg = load_tts_config()
    
    alerts = run_checks(config)
    
    for title, message, level in alerts:
        if not send_notification(title, message, level):
            print(f"Warning: failed to send notification: {title}")
    
    # Check reminders
    reminders = check_reminders()
    send_reminders(reminders, tts_cfg)
    
    return 0


def run_daemon() -> int:
    """Run as a background daemon."""
    config = load_config()
    tts_cfg = load_tts_config()
    poll_seconds = config.get("heartbeat", {}).get("poll_seconds", 60)
    
    # Write PID file
    ensure_dirs()
    SENTINEL_PID_FILE.write_text(str(os.getpid()))
    
    # Signal handler
    running = True
    
    def handle_signal(signum, frame):
        nonlocal running
        running = False
    
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    
    print(f"JARVIS Sentinel started (PID: {os.getpid()})")
    
    while running:
        try:
            alerts = run_checks(config)
            for title, message, level in alerts:
                send_notification(title, message, level)
            
            reminders = check_reminders()
            send_reminders(reminders, tts_cfg)
            
            time.sleep(poll_seconds)
        except Exception as e:
            print(f"Error in sentinel loop: {e}")
            time.sleep(10)
    
    # Cleanup
    SENTINEL_PID_FILE.unlink(missing_ok=True)
    print("JARVIS Sentinel stopped")
    
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jarvis-sentinel",
        description="JARVIS background sentinel for system monitoring and reminders"
    )
    parser.add_argument(
        "--once", "-o",
        action="store_true",
        help="Run checks once and exit"
    )
    parser.add_argument(
        "--status", "-s",
        action="store_true",
        help="Show current monitoring status"
    )
    parser.add_argument(
        "--check-cpu",
        action="store_true",
        help="Check CPU usage only"
    )
    
    args = parser.parse_args(argv)
    
    if args.status:
        config = load_config()
        tts_cfg = load_tts_config()
        print("JARVIS Sentinel Status")
        print("=" * 40)
        if SENTINEL_PID_FILE.exists():
            pid = SENTINEL_PID_FILE.read_text().strip()
            print(f"Running: PID {pid}")
        else:
            print("Not running")
        
        voice_reminders = config.get("heartbeat", {}).get("voice_reminders_enabled", True)
        print(f"Voice reminders: {'enabled' if voice_reminders else 'disabled'}")
        print(f"TTS provider: {tts_cfg.provider}")
        
        print("\nConfigured checks:")
        checks = config.get("heartbeat", {}).get("checks", {})
        for name, settings in checks.items():
            enabled = settings.get("enabled", True)
            interval = settings.get("interval_seconds", 900)
            print(f"  {name}: {'enabled' if enabled else 'disabled'} (interval: {interval}s)")
        
        return 0
    
    if args.check_cpu:
        alert = check_cpu(load_config())
        if alert:
            print(f"CPU Alert: {alert}")
            send_notification("JARVIS Alert", alert)
            speak_text(alert, load_tts_config())
        else:
            print("CPU: OK")
        return 0
    
    if args.once:
        return run_once()
    
    # Default: run as daemon
    return run_daemon()


if __name__ == "__main__":
    sys.exit(main())