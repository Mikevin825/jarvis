"""The heartbeat — the background loop that lets JARVIS act unspoken to.

Design rules, all taken from the spec and all built in from the start rather than
added after it annoys you:

* **Quiet by default.** Most checks produce nothing most of the time. Only
  something genuinely worth attention becomes a notice.
* **Never drop what you weren't there to see.** Notices are written to the inbox
  first and marked delivered only once shown — catch-up on return, never
  deliver-once-and-lose-it.
* **Respect quiet hours.** Non-urgent surfacing waits for waking hours; only
  urgent items interrupt.
* **Never block forever waiting on a human.** Nothing here waits on the user.
  Anything that would is deferred to the inbox with a safe default.
* **Survive restarts.** Due times persist, so a restart resumes the schedule
  instead of refiring everything.
* **No overlapping runs.** A check still working when its next turn comes due is
  skipped, not stacked.
* **Every surfaced item is dismissible.**

The loop is deliberately ignorant of which machine it is on, so moving it to an
always-on host later is a relocation, not a rewrite.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from datetime import time as dt_time
from pathlib import Path

from .checks import Check, CheckContext, CheckResult, build_checks
from .inbox import URGENT, Inbox, Notice
from .schedule import Schedule


def _parse_hhmm(value: str) -> dt_time | None:
    try:
        hour, minute = value.strip().split(":")
        return dt_time(int(hour), int(minute))
    except (ValueError, AttributeError):
        return None


class QuietHours:
    """A window during which only urgent things may interrupt."""

    def __init__(self, start: str, end: str, enabled: bool = True) -> None:
        self.start = _parse_hhmm(start)
        self.end = _parse_hhmm(end)
        self.enabled = enabled and self.start is not None and self.end is not None

    def active(self, moment: datetime) -> bool:
        if not self.enabled or self.start is None or self.end is None:
            return False
        now = moment.astimezone().time()
        if self.start <= self.end:
            return self.start <= now < self.end
        # Window crosses midnight, e.g. 22:00 -> 07:00.
        return now >= self.start or now < self.end

    def describe(self) -> str:
        if not self.enabled or self.start is None or self.end is None:
            return "disabled"
        return f"{self.start.strftime('%H:%M')}–{self.end.strftime('%H:%M')}"


class Heartbeat:
    """Runs the checks on a schedule and routes results to the inbox."""

    def __init__(
        self,
        schedule: Schedule,
        inbox: Inbox,
        config: dict,
        checks: list[Check] | None = None,
        log=None,
    ) -> None:
        self.schedule = schedule
        self.inbox = inbox
        self.config = config or {}
        self.quiet = QuietHours(
            self.config.get("quiet_hours_start", "22:00"),
            self.config.get("quiet_hours_end", "07:00"),
            bool(self.config.get("quiet_hours_enabled", True)),
        )
        self.poll_seconds = float(self.config.get("poll_seconds", 5))
        self._provider = None  # Set by the CLI when a provider is available
        self.checks = checks if checks is not None else build_checks(
            self.config.get("checks", {}),
            provider=getattr(self, "_provider", None),
        )
        self.log = log
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        # Register every check, preserving any existing due time.
        for check in self.checks:
            first_delay = float(
                (self.config.get("checks", {}).get(check.name) or {}).get(
                    "first_delay_seconds", 0
                )
            )
            self.schedule.ensure(check.name, check.interval_seconds, first_delay=first_delay)

    # -- lifecycle ----------------------------------------------------------

    def set_provider(self, provider) -> None:
        """Set the provider for checks that need one (e.g. the scout).

        Called by the CLI when a provider is available. Checks that need a
        provider are rebuilt with it.
        """
        self._provider = provider
        # Rebuild checks that need a provider.
        self.checks = build_checks(
            self.config.get("checks", {}),
            provider=provider,
        )

    @property
    def paused(self) -> bool:
        return self.schedule.paused

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self.run_forever, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    # -- the loop -----------------------------------------------------------

    def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - the loop must never die
                self._record("heartbeat", "error", f"{type(exc).__name__}: {exc}")
            self._stop.wait(self.poll_seconds)

    def tick(self, now: datetime | None = None) -> list[Notice]:
        """Run one pass. Returns notices created. Safe to call directly in tests."""
        moment = now or datetime.now(timezone.utc)

        if self.paused:
            return []

        created: list[Notice] = []
        for state in self.schedule.due(moment):
            check = next((c for c in self.checks if c.name == state.name), None)
            if check is None:
                continue
            notice = self.run_check(check, moment)
            if notice is not None:
                created.append(notice)
        return created

    def run_check(self, check: Check, now: datetime | None = None) -> Notice | None:
        """Run one check. Never raises; never stacks on an in-flight run."""
        moment = now or datetime.now(timezone.utc)

        state = self.schedule.checks.get(check.name)
        if state is None:
            return None
        if state.running:
            # Don't pile up overlapping runs — skip rather than stack.
            self._record(check.name, "skipped", "still running")
            return None

        self.schedule.mark_started(check.name)
        started = time.time()
        try:
            result = check.run(CheckContext(settings=state_settings(self.config, check), now=moment))
        except Exception as exc:  # noqa: BLE001 - one bad check must not stop the rest
            self.schedule.mark_finished(
                check.name,
                check.interval_seconds,
                status="error",
                summary=f"{type(exc).__name__}: {exc}",
                failed=True,
            )
            self._record(check.name, "error", f"{type(exc).__name__}: {exc}")
            return None

        elapsed = time.time() - started
        notice = None
        if result.surfaced:
            notice = self._surface(check.name, result, moment)

        self.schedule.mark_finished(
            check.name,
            check.interval_seconds,
            status="surfaced" if result.surfaced else "quiet",
            summary=result.summary or ("surfaced" if result.surfaced else "nothing"),
        )
        self._record(
            check.name,
            "surfaced" if result.surfaced else "quiet",
            result.summary or "",
            extra=f"{elapsed:.2f}s",
        )
        return notice

    # -- surfacing ----------------------------------------------------------

    def _surface(self, source: str, result: CheckResult, moment: datetime) -> Notice:
        """Turn a check result into a notice, respecting quiet hours.

        During quiet hours a non-urgent result is still recorded — it is simply
        held, and the catch-up-on-return path shows it later. Deferring must
        never mean dropping.
        """
        quiet_now = self.quiet.active(moment)
        if quiet_now and result.level != URGENT:
            # Hold it. `delivered=False` is what makes it appear on return.
            notice = self.inbox.add(
                source=source,
                title=result.title,
                body=(result.body + "\n(held until quiet hours ended)").strip(),
                level=result.level,
            )
            self._record(source, "held", f"quiet hours ({self.quiet.describe()})")
            return notice

        return self.inbox.add(
            source=source,
            title=result.title,
            body=result.body,
            level=result.level,
        )

    def _record(self, source: str, status: str, detail: str, extra: str = "") -> None:
        if self.log is not None:
            try:
                self.log(source=source, status=status, detail=detail, extra=extra)
            except Exception:  # noqa: BLE001
                pass

    # -- user-facing --------------------------------------------------------

    def catch_up(self, mark_delivered: bool = True) -> list[Notice]:
        """Everything that happened while the user was away.

        This is the anti-deliver-once-and-lose-it path: notices accumulate in
        the inbox whether or not anyone was watching, and are handed over here.
        """
        pending = self.inbox.undelivered()
        if mark_delivered and pending:
            self.inbox.mark_all_delivered()
        return pending


def state_settings(config: dict, check: Check) -> dict:
    """The per-check settings block from config, for a given check."""
    return ((config or {}).get("checks", {}) or {}).get(check.name, {}) or {}
