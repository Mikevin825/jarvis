"""The durable schedule.

The heartbeat's whole point is that it keeps its own time, so the record of when
each check is next due lives on disk, not in memory. Restarting the program must
not reset every timer, and must not fire everything at once on boot.

Writes are atomic (write-temp-then-rename) because a crash mid-write would
otherwise lose the schedule and cause exactly the mass-refire this exists to
prevent.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path


class ScheduleError(RuntimeError):
    """The schedule could not be read or written."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(text: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


@dataclass
class CheckState:
    """What we remember about one check between runs."""

    name: str
    next_due: datetime
    last_run: datetime | None = None
    last_status: str = ""
    last_summary: str = ""
    # Set while a run is in progress, so a second run cannot start on top of it.
    running: bool = False
    # Counts consecutive failures, so a persistently broken check can be backed
    # off instead of retried forever at full rate.
    failures: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "next_due": _iso(self.next_due),
            "last_run": _iso(self.last_run) if self.last_run else None,
            "last_status": self.last_status,
            "last_summary": self.last_summary,
            "running": self.running,
            "failures": self.failures,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "CheckState":
        next_due = _parse(raw.get("next_due", "")) or _now()
        return cls(
            name=raw.get("name", ""),
            next_due=next_due,
            last_run=_parse(raw.get("last_run", "") or ""),
            last_status=raw.get("last_status", ""),
            last_summary=raw.get("last_summary", ""),
            running=bool(raw.get("running", False)),
            failures=int(raw.get("failures", 0)),
        )


@dataclass
class Schedule:
    path: Path
    checks: dict[str, CheckState] = field(default_factory=dict)
    paused: bool = False

    # -- persistence --------------------------------------------------------

    def load(self) -> "Schedule":
        if not self.path.exists():
            return self
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScheduleError(f"could not read {self.path}: {exc}") from exc

        self.paused = bool(raw.get("paused", False))
        self.checks = {}
        for entry in raw.get("checks", []):
            state = CheckState.from_dict(entry)
            if state.name:
                self.checks[state.name] = state
        return self

    def save(self) -> None:
        payload = {
            "paused": self.paused,
            "saved_at": _iso(_now()),
            "checks": [c.to_dict() for c in self.checks.values()],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=".schedule-", suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp, self.path)
        except OSError as exc:
            raise ScheduleError(f"could not write {self.path}: {exc}") from exc

    # -- scheduling ---------------------------------------------------------

    def ensure(self, name: str, interval_seconds: float, *, first_delay: float = 0.0) -> CheckState:
        """Register a check, keeping its existing due time if we have one.

        This is what makes restarts safe: an existing check keeps its schedule
        rather than being reset to "due now".
        """
        existing = self.checks.get(name)
        if existing is not None:
            return existing

        state = CheckState(
            name=name, next_due=_now() + timedelta(seconds=first_delay)
        )
        self.checks[name] = state
        return state

    def due(self, now: datetime | None = None) -> list[CheckState]:
        """Checks that are due and not already running."""
        moment = now or _now()
        return [
            c
            for c in self.checks.values()
            if not c.running and c.next_due <= moment
        ]

    def mark_started(self, name: str) -> None:
        state = self.checks.get(name)
        if state is not None:
            state.running = True
            self.save()

    def mark_finished(
        self,
        name: str,
        interval_seconds: float,
        *,
        status: str,
        summary: str = "",
        failed: bool = False,
    ) -> None:
        state = self.checks.get(name)
        if state is None:
            return
        state.running = False
        state.last_run = _now()
        state.last_status = status
        state.last_summary = summary[:500]

        if failed:
            state.failures += 1
            # Back off a broken check so it does not retry at full rate forever.
            delay = interval_seconds * min(state.failures + 1, 8)
        else:
            state.failures = 0
            delay = interval_seconds

        state.next_due = _now() + timedelta(seconds=delay)
        self.save()

    def clear_running_flags(self) -> int:
        """Forget any in-flight markers left by a previous process.

        A crash mid-run would otherwise leave `running` set forever, and the
        check would never fire again — a silent failure that looks like the
        heartbeat simply went quiet.
        """
        cleared = 0
        for state in self.checks.values():
            if state.running:
                state.running = False
                cleared += 1
        if cleared:
            self.save()
        return cleared

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.save()

    def reset(self, name: str | None = None) -> None:
        """Make a check due immediately. Used by the CLI for testing."""
        if name is None:
            for state in self.checks.values():
                state.next_due = _now()
        elif name in self.checks:
            self.checks[name].next_due = _now()
        self.save()
