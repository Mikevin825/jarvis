"""The heartbeat command line.

Gives you direct control over the proactive side without starting a
conversation: run the loop, check its state, trigger a check on purpose, read
the inbox, and hit the kill switch.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

from .audit import AuditLog
from .config import ConfigError, load_config, load_dotenv
from .heartbeat import Heartbeat, Inbox, Schedule
from .heartbeat.checks import known_checks
from .paths import AUDIT_FILE, INBOX_FILE, PAUSE_FILE, SCHEDULE_FILE


def _build() -> tuple:
    load_dotenv()
    cfg = load_config()

    log = AuditLog(AUDIT_FILE)
    schedule = Schedule(SCHEDULE_FILE).load()
    inbox = Inbox(INBOX_FILE).load()

    hb_dict = {
        "poll_seconds": cfg.heartbeat.poll_seconds,
        "quiet_hours_enabled": cfg.heartbeat.quiet_hours_enabled,
        "quiet_hours_start": cfg.heartbeat.quiet_hours_start,
        "quiet_hours_end": cfg.heartbeat.quiet_hours_end,
        "checks": cfg.heartbeat.checks,
    }
    heartbeat = Heartbeat(schedule, inbox, hb_dict, log=log.write)
    return cfg, heartbeat, schedule, inbox


def _kill_switch_engaged() -> bool:
    return PAUSE_FILE.exists()


def _print_notice(notice) -> None:
    flag = "!" if notice.urgent else "·"
    print(f"  {flag} [{notice.id}] {notice.title}")
    if notice.body:
        for line in notice.body.splitlines():
            print(f"      {line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jarvis-heartbeat",
        description="Run and inspect JARVIS's proactive checks.",
    )
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="run the heartbeat loop in the foreground")
    run_p.add_argument(
        "--once", action="store_true", help="run one pass and exit"
    )
    run_p.add_argument(
        "--force",
        action="store_true",
        help="ignore the kill switch for this run",
    )

    sub.add_parser("status", help="show what the heartbeat is doing")
    sub.add_parser("inbox", help="list notices waiting for you")

    trig_p = sub.add_parser("trigger", help="make a check due immediately")
    trig_p.add_argument("check", nargs="?", help="check name, or all if omitted")

    sub.add_parser("dismiss", help="clear notices from the inbox")
    sub.add_parser("pause", help="kill switch: stop all proactive behaviour")
    sub.add_parser("resume", help="release the kill switch")
    sub.add_parser("reset", help="forget the schedule (fires everything next run)")
    sub.add_parser("checks", help="list the available checks")

    args = parser.parse_args(argv)

    if args.command == "checks":
        print("Available checks:")
        for name in known_checks():
            print(f"  {name}")
        print("\nEnable and tune them under heartbeat.checks in config.yaml.")
        return 0

    try:
        cfg, heartbeat, schedule, inbox = _build()
    except ConfigError as exc:
        print(f"configuration problem: {exc}", file=sys.stderr)
        return 2

    if args.command == "status":
        paused = _kill_switch_engaged()
        print(f"heartbeat enabled in config: {cfg.heartbeat.enabled}")
        print(f"kill switch (state/PAUSED):  {'ENGAGED — all proactive behaviour stopped' if paused else 'released'}")
        print(f"quiet hours:                 {heartbeat.quiet.describe()}")
        print(f"poll interval:               {heartbeat.poll_seconds}s")
        print(f"pending notices:             {inbox.count_pending()}")
        print(f"undelivered (catch-up):      {len(inbox.undelivered())}")
        print(f"schedule file:               {schedule.path}")
        print("\nchecks:")
        if not schedule.checks:
            print("  (none registered yet)")
        for state in sorted(schedule.checks.values(), key=lambda s: s.name):
            due = state.next_due.astimezone().strftime("%H:%M:%S")
            flag = " [running]" if state.running else ""
            print(
                f"  {state.name:<10} next {due}  last {state.last_status or '-':<9}"
                f"{flag}  {state.last_summary[:40]}"
            )
        return 0

    if args.command == "inbox":
        pending = inbox.pending()
        if not pending:
            print("The inbox is empty.")
            return 0
        print(f"{len(pending)} notice(s):\n")
        for notice in pending:
            _print_notice(notice)
        print("\nDismiss with: jarvis-heartbeat dismiss")
        return 0

    if args.command == "dismiss":
        count = inbox.dismiss_all()
        print(f"Dismissed {count} notice(s).")
        return 0

    if args.command == "pause":
        PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PAUSE_FILE.write_text(
            "Kill switch engaged. Delete this file (or run 'resume') to restart "
            "proactive behaviour.\n",
            encoding="utf-8",
        )
        schedule.set_paused(True)
        print("Kill switch ENGAGED — all proactive behaviour is stopped.")
        print("You can still talk to JARVIS normally.")
        return 0

    if args.command == "resume":
        PAUSE_FILE.unlink(missing_ok=True)
        schedule.set_paused(False)
        print("Kill switch released — proactive behaviour resumes.")
        return 0

    if args.command == "reset":
        schedule.reset()
        print("Schedule reset — every check is due on the next run.")
        return 0

    if args.command == "trigger":
        if args.check and args.check not in schedule.checks:
            print(
                f"No check called '{args.check}'. Known: "
                f"{', '.join(sorted(schedule.checks)) or 'none'}",
                file=sys.stderr,
            )
            return 2
        schedule.reset(args.check)
        target = args.check or "all checks"
        print(f"Triggered {target} — due on the next pass.")
        return 0

    if args.command == "run":
        if _kill_switch_engaged() and not args.force:
            print(
                "The kill switch is engaged (state/PAUSED).\n"
                "  Release it with:  jarvis-heartbeat resume\n"
                "  Or override once: jarvis-heartbeat run --force",
                file=sys.stderr,
            )
            return 2

        # A previous crash could leave a check marked running forever, which
        # would silently stop it firing again.
        cleared = schedule.clear_running_flags()
        if cleared:
            print(f"(cleared {cleared} stale in-flight marker(s) from a previous run)")

        if args.once:
            created = heartbeat.tick()
            if not created:
                print("Nothing surfaced this pass.")
            for notice in created:
                _print_notice(notice)
            return 0

        print(
            f"Heartbeat running. {len(heartbeat.checks)} check(s), "
            f"quiet hours {heartbeat.quiet.describe()}. Ctrl-C to stop.\n"
        )
        try:
            while True:
                created = heartbeat.tick()
                for notice in created:
                    stamp = datetime.now().astimezone().strftime("%H:%M:%S")
                    _print_notice(notice)
                time.sleep(heartbeat.poll_seconds)
        except KeyboardInterrupt:
            print("\nHeartbeat stopped.")
        return 0

    parser.print_help()
    return 0
