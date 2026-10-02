"""The checks the heartbeat runs.

Each check is one small self-contained unit: when it runs, what it looks at, and
how it decides whether the result is worth surfacing. Adding a new one means
writing a class here and naming it in config.yaml — the heartbeat loop itself
never changes.

The rule every check obeys: **most runs should produce nothing.** A check returns
a `CheckResult` with `surfaced=False` when there is nothing worth saying. An
assistant that cries wolf gets muted, and a muted assistant is useless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol

from .inbox import NORMAL, QUIET, URGENT


@dataclass
class CheckResult:
    """What a check decided."""

    # True only when this is genuinely worth the user's attention.
    surfaced: bool = False
    title: str = ""
    body: str = ""
    level: str = NORMAL
    # Free-form, for the audit log — recorded even when nothing surfaced, so a
    # quiet check is still visibly alive rather than silently broken.
    summary: str = ""


@dataclass
class CheckContext:
    """Everything a check is allowed to touch."""

    settings: dict = field(default_factory=dict)
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Lets a check reuse the assistant's own tools rather than duplicating them.
    tools: object | None = None


class Check(Protocol):
    name: str
    interval_seconds: float

    def run(self, ctx: CheckContext) -> CheckResult:  # pragma: no cover - protocol
        ...


# --------------------------------------------------------------------------
# Built-in checks
# --------------------------------------------------------------------------


class ClockCheck:
    """A deliberately trivial check, for verifying the loop end to end.

    With `trigger_file` set it surfaces whenever that file exists — a condition
    you can create on purpose. Without it, it surfaces on the hour.
    """

    name = "clock"

    def __init__(self, interval_seconds: float, settings: dict) -> None:
        self.interval_seconds = interval_seconds
        self.settings = settings

    def run(self, ctx: CheckContext) -> CheckResult:
        trigger = self.settings.get("trigger_file")
        if trigger:
            from pathlib import Path

            path = Path(trigger).expanduser()
            if path.exists():
                try:
                    detail = path.read_text(encoding="utf-8").strip()
                except OSError:
                    detail = ""
                return CheckResult(
                    surfaced=True,
                    title=self.settings.get("trigger_title", "Test condition met"),
                    body=detail or f"The trigger file {path} exists.",
                    level=self.settings.get("level", NORMAL),
                    summary="trigger file present",
                )
            return CheckResult(summary="no trigger file")

        now = ctx.now.astimezone()
        if now.minute < 5:
            return CheckResult(
                surfaced=True,
                title=f"It is {now.strftime('%H:%M')}",
                body=f"Now {now.strftime('%A %d %B, %H:%M')}.",
                level=QUIET,
                summary="hourly",
            )
        return CheckResult(summary="nothing due")


class NoteCountCheck:
    """Surfaces when the number of notes crosses a threshold.

    Exists mainly as a realistic example of a check that is quiet almost always:
    it reports only on an exact crossing, so it fires once and then stays silent
    until the count moves again.
    """

    name = "notes"

    def __init__(self, interval_seconds: float, settings: dict) -> None:
        self.interval_seconds = interval_seconds
        self.settings = settings

    def run(self, ctx: CheckContext) -> CheckResult:
        from ..paths import NOTES_DIR, ensure_dirs

        ensure_dirs()
        count = len(list(NOTES_DIR.glob("*.md")))
        threshold = int(self.settings.get("threshold", 10))
        if count >= threshold:
            return CheckResult(
                surfaced=True,
                title=f"You have {count} notes",
                body=(
                    f"There are now {count} notes, at or past the threshold of "
                    f"{threshold}. Worth a tidy-up?"
                ),
                level=self.settings.get("level", QUIET),
                summary=f"{count} notes",
            )
        return CheckResult(summary=f"{count} notes")


class MessageWatchCheck:
    """Surfaces unread messages that have been sitting unread for a while.

    The "for a while" part is the point: a check that fires the instant anything
    arrives is a notification, not an assistant.
    """

    name = "messages"

    def __init__(self, interval_seconds: float, settings: dict) -> None:
        self.interval_seconds = interval_seconds
        self.settings = settings

    def run(self, ctx: CheckContext) -> CheckResult:
        from ..paths import MESSAGES_FILE

        if not MESSAGES_FILE.exists():
            return CheckResult(summary="no store")
        try:
            import json

            store = json.loads(MESSAGES_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return CheckResult(summary="unreadable store")

        min_age = float(self.settings.get("min_age_minutes", 60))
        cutoff = ctx.now - timedelta(minutes=min_age)
        stale = []
        for message in store.get("inbox", []):
            if message.get("read"):
                continue
            try:
                when = datetime.fromisoformat(message.get("received", ""))
            except (TypeError, ValueError):
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when <= cutoff:
                stale.append(message)

        if stale:
            who = ", ".join(m.get("from", "someone") for m in stale[:3])
            return CheckResult(
                surfaced=True,
                title=f"{len(stale)} unread message(s) waiting",
                body=f"Unread for over {int(min_age)} minutes, from {who}.",
                level=self.settings.get("level", NORMAL),
                summary=f"{len(stale)} stale unread",
            )
        return CheckResult(summary="no stale unread")


# --------------------------------------------------------------------------

_REGISTRY = {
    ClockCheck.name: ClockCheck,
    NoteCountCheck.name: NoteCountCheck,
    MessageWatchCheck.name: MessageWatchCheck,
}


def build_checks(config: dict) -> list[Check]:
    """Construct the enabled checks from the `heartbeat.checks` config block."""
    built: list[Check] = []
    for name, settings in (config or {}).items():
        settings = settings or {}
        if not settings.get("enabled", True):
            continue
        factory = _REGISTRY.get(name)
        if factory is None:
            # Unknown check name in config: skip it rather than crash the loop.
            continue
        interval = float(settings.get("interval_seconds", 900))
        built.append(factory(interval, settings))
    return built


def known_checks() -> list[str]:
    return sorted(_REGISTRY)
