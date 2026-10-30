"""Desktop entry point: python -m jarvis.desktop

Starts the voice loop and shows the panel. This is what the .desktop launcher
runs, so JARVIS opens like an application rather than a terminal command.
"""

from __future__ import annotations

import sys

from ..cli import _build_brain
from ..config import ConfigError
from ..desktop import DesktopPanel, GuiGate
from ..paths import AUDIT_FILE, INBOX_FILE, PAUSE_FILE, SCHEDULE_FILE
from ..providers import ProviderError
from ..tools.reminders import start_scheduler
from ..voice import SpeechError, TranscriptionError, build_speaker, build_transcriber
from ..voice.keys import KeyCombo
from ..voice.loop import VoiceConfig, VoiceLoop


def main(argv: list[str] | None = None) -> int:
    from ..audit import AuditLog
    from ..heartbeat import Heartbeat, Inbox, Schedule

    # Start the reminder scheduler so notifications work immediately
    # when reminders become due (even before any reminder is set)
    start_scheduler()

    # The panel needs the gate before the brain is built, because the gate is
    # attached to the registry the brain runs tools through. A tiny stand-in is
    # used first and swapped for the real one once the window exists.
    panel_ref: dict = {}

    class DeferredGuiGate:
        """Forwards to the real GUI gate once the panel is constructed.

        Needed because the gate must be attached to the registry before the
        window exists, but the window is what knows how to ask. A deferral, not
        a bypass: if the panel never appears, this denies.
        """

        def confirm(self, request):
            from ..gate import Decision

            real = panel_ref.get("gate")
            if real is None:
                return Decision(False, "the window is not available to confirm in")
            return real.confirm(request)

    try:
        cfg, brain, store, _session_store, _provider = _build_brain(gate=DeferredGuiGate())
    except ConfigError as exc:
        print(f"configuration problem: {exc}", file=sys.stderr)
        return 2
    except ProviderError as exc:
        print(f"cannot start: {exc}", file=sys.stderr)
        return 2

    try:
        transcriber = build_transcriber(cfg.stt)
        speaker = build_speaker(cfg.tts)
    except (TranscriptionError, SpeechError) as exc:
        print(f"cannot start voice: {exc}", file=sys.stderr)
        return 2

    log = AuditLog(AUDIT_FILE, enabled=cfg.rails.audit_log)
    brain.registry.on_audit = lambda src, status, detail: log.write(
        source=src, status=status, detail=detail
    )

    ptt = KeyCombo(cfg.voice.ptt_key)
    if not ptt.is_valid:
        print(
            f"voice.ptt_key is not a usable binding: {cfg.voice.ptt_key!r}\n"
            "  Use a single key like 'f9', or a combo like '<ctrl>+<alt>+j'.",
            file=sys.stderr,
        )
        return 2

    loop = VoiceLoop(
        brain,
        transcriber,
        speaker,
        config=VoiceConfig(
            ptt_key=cfg.voice.ptt_key,
            interrupt_key=cfg.voice.interrupt_key,
            speak_replies=cfg.voice.speak_replies,
            show_transcript=cfg.voice.show_transcript,
            thinking_cue=cfg.voice.thinking_cue,
            min_sentence_chars=cfg.voice.min_sentence_chars,
        ),
        registry=brain.registry,
    )

    panel = DesktopPanel(
        loop,
        assistant_name=cfg.assistant.name,
        ptt_description=ptt.describe(),
        interrupt_description=cfg.voice.interrupt_key.upper(),
    )

    # Now that the window exists, the real gate can ask in it.
    panel_ref["gate"] = GuiGate(panel.ask_confirmation)
    loop._on_state_cb = panel.on_state
    loop._on_turn_cb = panel.on_turn
    loop._on_tool_cb = panel.on_tool

    # Listen for the push-to-talk key. The panel's button works either way, so a
    # failure here degrades rather than breaks.
    loop._install_listener()

    # The heartbeat runs alongside, so proactive notices keep arriving while the
    # window is open.
    heartbeat = None
    inbox = Inbox(INBOX_FILE).load()
    if cfg.heartbeat.enabled and not PAUSE_FILE.exists():
        hb_dict = {
            "poll_seconds": cfg.heartbeat.poll_seconds,
            "quiet_hours_enabled": cfg.heartbeat.quiet_hours_enabled,
            "quiet_hours_start": cfg.heartbeat.quiet_hours_start,
            "quiet_hours_end": cfg.heartbeat.quiet_hours_end,
            "checks": cfg.heartbeat.checks,
        }
        schedule = Schedule(SCHEDULE_FILE).load()
        schedule.clear_running_flags()
        heartbeat = Heartbeat(schedule, inbox, hb_dict, log=log.write)

        for notice in heartbeat.catch_up(mark_delivered=True):
            panel._append("meta", f"while you were away: {notice.title}")

        heartbeat.start()

    try:
        panel.run()
    finally:
        if heartbeat is not None:
            heartbeat.stop()
        loop.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
