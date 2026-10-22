"""The heartbeat must stay quiet, hold what it notices, and survive restarts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jarvis.heartbeat import Heartbeat, Inbox, Schedule
from jarvis.heartbeat.checks import CheckContext, CheckResult
from jarvis.heartbeat.inbox import NORMAL, QUIET, URGENT
from jarvis.heartbeat.loop import QuietHours

WAT = timezone(timedelta(hours=1))


class StubCheck:
    """A check whose result the test controls."""

    def __init__(self, name, result, interval=60):
        self.name = name
        self.interval_seconds = interval
        self._result = result
        self.runs = 0

    def run(self, ctx):
        self.runs += 1
        return self._result


def build(state_dir, checks, config=None):
    schedule = Schedule(state_dir / "schedule.json").load()
    inbox = Inbox(state_dir / "inbox.json").load()
    cfg = {"checks": {}, "quiet_hours_enabled": False}
    cfg.update(config or {})
    hb = Heartbeat(schedule, inbox, cfg, checks=checks)
    return hb, schedule, inbox


# -- quiet by default -------------------------------------------------------


def test_a_quiet_check_creates_no_notice(state_dir):
    hb, _schedule, inbox = build(
        state_dir, [StubCheck("quiet", CheckResult(surfaced=False, summary="nothing"))]
    )
    created = hb.tick()
    assert created == []
    assert inbox.count_pending() == 0


def test_a_surfacing_check_creates_exactly_one_notice(state_dir):
    hb, _schedule, inbox = build(
        state_dir,
        [StubCheck("loud", CheckResult(surfaced=True, title="Something", body="Detail"))],
    )
    created = hb.tick()
    assert len(created) == 1
    assert inbox.count_pending() == 1


# -- catch-up: held, never lost ---------------------------------------------


def test_notice_is_held_until_the_user_returns(state_dir):
    """The deliver-once-and-lose-it failure this design exists to prevent."""
    hb, _schedule, inbox = build(
        state_dir, [StubCheck("x", CheckResult(surfaced=True, title="While away"))]
    )
    hb.tick()

    # The user was not looking. On return:
    missed = hb.catch_up()
    assert len(missed) == 1
    assert missed[0].title == "While away"
    # And a second catch-up must not repeat it.
    assert hb.catch_up() == []


def test_a_notice_survives_a_restart(state_dir):
    hb, _schedule, _inbox = build(
        state_dir, [StubCheck("x", CheckResult(surfaced=True, title="Persisted"))]
    )
    hb.tick()

    fresh_inbox = Inbox(state_dir / "inbox.json").load()
    assert fresh_inbox.count_pending() == 1
    assert fresh_inbox.pending()[0].title == "Persisted"


def test_dismissing_clears_a_notice(state_dir):
    hb, _schedule, inbox = build(
        state_dir, [StubCheck("x", CheckResult(surfaced=True, title="Dismiss me"))]
    )
    hb.tick()
    assert inbox.count_pending() == 1
    assert inbox.dismiss_all() == 1
    assert inbox.count_pending() == 0


# -- quiet hours ------------------------------------------------------------


def test_quiet_hours_window_across_midnight():
    q = QuietHours("22:00", "07:00")
    assert q.active(datetime(2026, 10, 2, 23, 30, tzinfo=WAT)) is True
    assert q.active(datetime(2026, 10, 2, 3, 0, tzinfo=WAT)) is True
    assert q.active(datetime(2026, 10, 2, 12, 0, tzinfo=WAT)) is False


def test_quiet_hours_window_within_a_day():
    q = QuietHours("09:00", "17:00")
    assert q.active(datetime(2026, 10, 2, 12, 0, tzinfo=WAT)) is True
    assert q.active(datetime(2026, 10, 2, 20, 0, tzinfo=WAT)) is False


def test_quiet_hours_can_be_disabled():
    q = QuietHours("22:00", "07:00", enabled=False)
    assert q.active(datetime(2026, 10, 2, 2, 0, tzinfo=WAT)) is False


def _force_due(schedule, name: str, moment: datetime) -> None:
    """Make a check due at `moment`, regardless of when it was registered.

    `Schedule.ensure` stamps `next_due` with the *real* clock, so a test that
    ticks with a fixed datetime only works while that datetime is still in the
    future. Pinning it here keeps the test meaningful on any day.
    """
    state = schedule.checks.get(name)
    if state is not None:
        state.next_due = moment


def test_non_urgent_notice_is_held_during_quiet_hours_not_dropped(state_dir):
    """Deferring must never mean discarding."""
    hb, schedule, inbox = build(
        state_dir,
        [StubCheck("x", CheckResult(surfaced=True, title="Held", level=NORMAL))],
        config={
            "quiet_hours_enabled": True,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "07:00",
        },
    )
    night = datetime(2026, 10, 2, 23, 30, tzinfo=WAT)
    _force_due(schedule, "x", night)
    hb.tick(now=night)

    # It exists, and it is still waiting to be shown.
    assert inbox.count_pending() == 1
    assert len(inbox.undelivered()) == 1


def test_urgent_notice_interrupts_even_in_quiet_hours(state_dir):
    hb, schedule, inbox = build(
        state_dir,
        [StubCheck("x", CheckResult(surfaced=True, title="Urgent", level=URGENT))],
        config={
            "quiet_hours_enabled": True,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "07:00",
        },
    )
    night = datetime(2026, 10, 2, 23, 30, tzinfo=WAT)
    _force_due(schedule, "x", night)
    hb.tick(now=night)
    assert inbox.count_pending() == 1


# -- scheduling -------------------------------------------------------------


def test_schedule_persists_and_does_not_refire_on_restart(state_dir):
    hb, schedule, _inbox = build(
        state_dir, [StubCheck("x", CheckResult(surfaced=False))]
    )
    hb.tick()  # runs it once, sets next_due forward

    reloaded = Schedule(state_dir / "schedule.json").load()
    assert reloaded.due() == [], "a restart must not refire everything"


def test_overlapping_runs_are_skipped_not_stacked(state_dir):
    check = StubCheck("slow", CheckResult(surfaced=False))
    hb, schedule, _inbox = build(state_dir, [check])
    schedule.mark_started("slow")

    hb.run_check(check)
    assert check.runs == 0, "an in-flight check must not start again"


def test_stale_running_flag_is_recovered_after_a_crash(state_dir):
    """Otherwise a crashed check would silently never fire again."""
    schedule = Schedule(state_dir / "schedule.json").load()
    schedule.ensure("x", 60)
    schedule.mark_started("x")
    assert schedule.checks["x"].running is True

    assert schedule.clear_running_flags() == 1
    assert schedule.checks["x"].running is False


def test_a_failing_check_backs_off_instead_of_retrying_at_full_rate(state_dir):
    hb, schedule, _inbox = build(
        state_dir, [StubCheck("boom", CheckResult(surfaced=False))]
    )
    schedule.ensure("boom", 60)

    schedule.mark_finished("boom", 60, status="error", failed=True)
    first = schedule.checks["boom"].next_due
    schedule.mark_finished("boom", 60, status="error", failed=True)
    second = schedule.checks["boom"].next_due

    assert second > first, "consecutive failures must widen the interval"


def test_a_broken_check_does_not_stop_the_others(state_dir):
    class Exploding:
        name = "exploding"
        interval_seconds = 60

        def run(self, ctx):
            raise RuntimeError("check is broken")

    good = StubCheck("good", CheckResult(surfaced=True, title="Still works"))
    hb, _schedule, inbox = build(state_dir, [Exploding(), good])
    hb.tick()

    assert inbox.count_pending() == 1, "one bad check must not silence the rest"


# -- the kill switch --------------------------------------------------------


def test_paused_heartbeat_does_nothing(state_dir):
    hb, schedule, inbox = build(
        state_dir, [StubCheck("x", CheckResult(surfaced=True, title="Should not appear"))]
    )
    schedule.set_paused(True)
    assert hb.tick() == []
    assert inbox.count_pending() == 0


def test_resuming_restores_behaviour(state_dir):
    hb, schedule, _inbox = build(
        state_dir, [StubCheck("x", CheckResult(surfaced=True, title="Back"))]
    )
    schedule.set_paused(True)
    hb.tick()
    schedule.set_paused(False)
    assert len(hb.tick()) == 1
