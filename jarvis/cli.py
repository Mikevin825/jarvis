"""Text entry point.

The plain-text interface. It stays alive for the life of the project: it is how
every future change gets debugged without talking to the computer, and it is the
graceful fallback when audio misbehaves.

Reads from the terminal when interactive, or from stdin when piped, so the same
loop can be driven by a script or a test.
"""

from __future__ import annotations

import argparse
import sys

from .brain import Brain, Chunk, ToolRun
from .config import ConfigError, load_config, load_dotenv
from .cost import CostTracker
from .gate import CliGate, DenyAllGate, NoHumanGate
from .memory import MemoryStore
from .paths import (
    AUDIT_FILE,
    COST_FILE,
    INBOX_FILE,
    MEMORY_FILE,
    PAUSE_FILE,
    SCHEDULE_FILE,
)
from .prompts import build_system_prompt
from .providers import ProviderError, build_provider
from .tools import build_registry

EXIT_WORDS = {"/quit", "/exit", "/q"}


def _build_brain(gate=None) -> tuple:
    load_dotenv()
    cfg = load_config()

    store = MemoryStore(MEMORY_FILE)
    store.load()

    provider = build_provider(cfg.brain)
    registry = build_registry(
        store,
        extra_gated=cfg.rails.extra_gated_tools,
        ungated=cfg.rails.ungated_tools,
    )

    # The gate is attached to the registry, so it covers every consequential
    # action regardless of where the turn came from.
    registry.gate = gate if gate is not None else DenyAllGate()

    brain = Brain(
        provider,
        build_system_prompt(cfg.assistant),
        registry,
        memory_selector=lambda turn: store.render(store.relevant(turn)),
        prompt_builder=lambda facts: build_system_prompt(cfg.assistant, facts),
    )
    return cfg, brain, store


def _fmt_args(args: dict) -> str:
    if not args:
        return ""
    return " " + " ".join(f"{k}={v!r}" for k, v in args.items())


def _run_turn(
    brain: Brain,
    name: str,
    text: str,
    verbose_tools: bool = True,
    tracker=None,
) -> None:
    """Run one turn, streaming the reply to the terminal.

    Tool activity is shown on its own line so it is always visible what the
    assistant actually did, not just what it said. The name prefix is printed
    only once real text arrives, so a failure before any output never leaves a
    dangling prompt on screen.
    """
    spoke = False
    try:
        for event in brain.ask(text):
            if isinstance(event, ToolRun):
                if verbose_tools:
                    if spoke:
                        print()
                        spoke = False
                    if event.gated:
                        status = "NEEDS YOUR OK"
                    else:
                        status = "ok" if event.ok else "FAILED"
                    print(f"  · {event.name}{_fmt_args(event.args)} → {status}")
                    if not event.ok and not event.gated:
                        print(f"    {event.content}")
            elif isinstance(event, Chunk):
                if not spoke:
                    print(f"{name} › ", end="", flush=True)
                    spoke = True
                print(event.text, end="", flush=True)
    except ProviderError as exc:
        # A network call failed. Shrug it off, say so clearly, keep the session.
        if spoke:
            print()
        print(f"[brain unavailable] {exc}")
        return

    if tracker is not None:
        # Usage from the last provider call of the turn.
        usage = getattr(brain, "last_usage", None)
        if usage:
            tracker.record(usage)

    if spoke:
        print()
    else:
        print(f"{name} › (no reply)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jarvis", description="Talk to JARVIS in plain text."
    )
    parser.add_argument(
        "-m",
        "--message",
        action="append",
        default=[],
        help="send a message non-interactively and exit (repeatable)",
    )
    parser.add_argument(
        "--show-transcript",
        action="store_true",
        help="print the in-memory history after the run (debugging aid)",
    )
    parser.add_argument(
        "--tools",
        action="store_true",
        help="list the registered tools and exit",
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help="start the push-to-talk voice interface instead of typing",
    )
    parser.add_argument(
        "--say",
        metavar="TEXT",
        help="speak this text aloud and exit (tests the voice output path)",
    )
    parser.add_argument(
        "--hear",
        metavar="WAV",
        help="transcribe an audio file and exit (tests the ears in isolation)",
    )
    parser.add_argument(
        "--voice-file",
        metavar="WAV",
        help=(
            "run one complete spoken turn from a wav file: transcribe, think, "
            "speak (tests the whole voice path without a microphone)"
        ),
    )
    parser.add_argument(
        "--voices",
        action="store_true",
        help="list the ElevenLabs voices your key can use, then exit",
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        help="show everything JARVIS remembers, and where it is stored",
    )
    parser.add_argument(
        "--inbox",
        action="store_true",
        help="show notices the heartbeat has surfaced, then exit",
    )
    parser.add_argument(
        "--dismiss",
        action="store_true",
        help="clear all notices from the inbox, then exit",
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        help="kill switch: stop all proactive behaviour (you can still talk)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="release the kill switch and resume proactive behaviour",
    )
    parser.add_argument(
        "--no-heartbeat",
        action="store_true",
        help="start without the background heartbeat",
    )
    parser.add_argument(
        "--rails",
        action="store_true",
        help="show the safety posture: what is gated, what the audit log holds",
    )
    parser.add_argument(
        "--audit",
        metavar="N",
        nargs="?",
        const=40,
        type=int,
        help="show the last N audit entries (default 40)",
    )
    parser.add_argument(
        "--cost",
        action="store_true",
        help="show the model usage and cost tally",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "auto-approve consequential actions. Intended for scripted runs "
            "where you have already decided — never for interactive use."
        ),
    )
    args = parser.parse_args(argv)

    try:
        # The gate is chosen before the brain is built, because it is attached
        # to the registry the brain runs tools through.
        interactive = sys.stdin.isatty() and not args.message and not args.yes
        if args.yes:
            from .gate import AutoApproveGate

            gate = AutoApproveGate()
        elif interactive:
            gate = CliGate()
        else:
            # Non-interactive without --yes: nobody is present to approve, so
            # consequential actions are refused rather than assumed.
            gate = NoHumanGate()
        cfg, brain, store = _build_brain(gate=gate)
    except ConfigError as exc:
        print(f"configuration problem: {exc}", file=sys.stderr)
        return 2
    except ProviderError as exc:
        print(f"cannot start: {exc}", file=sys.stderr)
        return 2

    name = cfg.assistant.name

    # -- the rails: posture, audit trail, cost -------------------------------
    from .audit import AuditLog
    from .heartbeat import Heartbeat, Inbox, Schedule

    log = AuditLog(AUDIT_FILE, enabled=cfg.rails.audit_log)
    tracker = CostTracker(COST_FILE, model=cfg.brain.model).load()
    hb_schedule = Schedule(SCHEDULE_FILE).load()
    inbox = Inbox(INBOX_FILE).load()

    # The audit trail records what was asked for as well as what happened.
    brain.registry.on_audit = lambda src, status, detail: log.write(
        source=src, status=status, detail=detail
    )
    # Usage is recorded per provider call, so a turn that ran several tool
    # rounds is not undercounted.
    brain.on_usage = tracker.record

    if args.rails:
        print("Safety posture\n" + "=" * 60)
        print(f"  confirm consequential actions: {cfg.rails.confirm_consequential}")
        print(f"  audit log:                     {cfg.rails.audit_log}  ({AUDIT_FILE})")
        print(f"  cost tracking:                 {cfg.rails.show_cost}")
        print(f"  kill switch:                   {'ENGAGED' if PAUSE_FILE.exists() else 'released'}")
        print("\nNever without asking (your list):")
        for item in ("spend money", "send messages", "delete data", "change settings"):
            print(f"  - {item}")
        print("\nGated tools:")
        for tool_name in brain.registry.consequential_names():
            tool = brain.registry.get(tool_name)
            print(f"  - {tool_name}: {tool.confirm_prompt or 'consequential'}")
        extra = cfg.rails.extra_gated_tools
        if extra:
            print(f"\nAdditionally gated by config: {', '.join(extra)}")
        if cfg.rails.ungated_tools:
            print(f"Exempted by config (loosened): {', '.join(cfg.rails.ungated_tools)}")
        print(
            "\nEverything else — lookups, reads, opens — runs without asking."
        )
        return 0

    if args.audit is not None:
        lines = log.tail(args.audit)
        if not lines:
            print("The audit log is empty.")
            return 0
        print(f"Last {len(lines)} audit entries ({AUDIT_FILE}):\n")
        for line in lines:
            print(f"  {line}")
        return 0

    if args.cost:
        print(f"Model: {cfg.brain.model}")
        print(f"  session:  {tracker.summary()}")
        lt = tracker.lifetime
        print(
            f"  lifetime: {lt.calls} calls, {lt.prompt_tokens:,} in / "
            f"{lt.output_tokens:,} out, ~${lt.cost_usd:.4f}"
        )
        print("\nToken counts are exact from the provider; cost uses list prices")
        print("and is an estimate. Adjust in jarvis/cost.py if your rates differ.")
        return 0

    if args.pause:
        PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PAUSE_FILE.write_text(
            "Kill switch engaged. Delete this file or run --resume.\n",
            encoding="utf-8",
        )
        hb_schedule.set_paused(True)
        log.write(source="kill-switch", status="engaged", detail="all proactive behaviour stopped")
        print("Kill switch ENGAGED — all proactive behaviour stopped.")
        print("You can still talk to JARVIS normally. Resume with --resume.")
        return 0

    if args.resume:
        PAUSE_FILE.unlink(missing_ok=True)
        hb_schedule.set_paused(False)
        log.write(source="kill-switch", status="released", detail="proactive behaviour resumed")
        print("Kill switch released — proactive behaviour resumes.")
        return 0

    if args.inbox:
        pending = inbox.pending()
        if not pending:
            print("The inbox is empty.")
            return 0
        print(f"{len(pending)} notice(s):\n")
        for notice in pending:
            flag = "!" if notice.urgent else "·"
            print(f"  {flag} [{notice.id}] {notice.title}")
            if notice.body:
                for line in notice.body.splitlines():
                    print(f"      {line}")
        print("\nClear them with: jarvis --dismiss")
        return 0

    if args.dismiss:
        count = inbox.dismiss_all()
        print(f"Dismissed {count} notice(s).")
        return 0

    # -- show long-term memory ------------------------------------------------
    if args.memory:
        facts = store.facts()
        print(f"Long-term memory — {len(facts)} fact(s)")
        print(f"stored at: {store.path}\n")
        if not facts:
            print("  (nothing remembered yet)")
        else:
            for fact in facts:
                print(f"  {fact.id} | {fact.text}")
        print(
            "\nThis file is plain text: open it and edit a line to correct or "
            "delete a fact.\nJARVIS reads it at the start of every conversation."
        )
        return 0

    # -- list the voices an ElevenLabs key can actually use ------------------
    if args.voices:
        from .voice import SpeechError
        from .voice.tts import ElevenLabsSpeaker

        # Read the key from the provider block, not the active provider — the
        # point of this command is to check a key before switching to it.
        key = cfg.tts.api_keys.get("elevenlabs")
        if not key:
            print(
                "No ELEVENLABS_API_KEY found in .env, so there are no voices to "
                "list.\n  Add it to ~/jarvis/.env as:  ELEVENLABS_API_KEY=sk_...",
                file=sys.stderr,
            )
            return 2
        speaker = ElevenLabsSpeaker(key, voice_id=cfg.tts.voice)
        try:
            voices = speaker.list_voices()
        except SpeechError as exc:
            print(f"cannot list voices: {exc}", file=sys.stderr)
            return 2
        print(f"{len(voices)} voice(s) available to this key:\n")
        for voice_id, voice_name in voices:
            print(f"  {voice_id}  {voice_name}")
        print(
            "\nPut the id you want in config.yaml under tts.elevenlabs.voice."
        )
        return 0

    # -- voice output only: speak and exit (isolates the mouth) --------------
    if args.say is not None:
        from .voice import SpeechError, build_speaker

        try:
            build_speaker(cfg.tts).speak(args.say)
        except SpeechError as exc:
            print(f"cannot speak: {exc}", file=sys.stderr)
            return 2
        return 0

    # -- ears only: transcribe a file and exit (isolates the ears) -----------
    if args.hear is not None:
        from pathlib import Path

        from .voice import TranscriptionError, build_transcriber

        path = Path(args.hear)
        try:
            text = build_transcriber(cfg.stt).transcribe(path)
        except TranscriptionError as exc:
            print(f"cannot transcribe: {exc}", file=sys.stderr)
            return 2
        print(text or "(heard nothing)")
        return 0

    # -- one full spoken turn from a file (isolates nothing — tests it all) --
    if args.voice_file is not None:
        from pathlib import Path

        from .voice import (
            SpeechError,
            TranscriptionError,
            build_speaker,
            build_transcriber,
        )
        from .voice.loop import VoiceConfig, VoiceLoop

        try:
            transcriber = build_transcriber(cfg.stt)
            speaker = build_speaker(cfg.tts)
        except (TranscriptionError, SpeechError) as exc:
            print(f"cannot start voice: {exc}", file=sys.stderr)
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
        path = Path(args.voice_file)
        if not path.exists():
            print(f"no such file: {path}", file=sys.stderr)
            return 2
        loop.handle_recording(path, consume=False)  # keep the fixture
        return 0

    # -- the voice interface -------------------------------------------------
    if args.voice:
        from .voice import (
            CaptureError,
            SpeechError,
            TranscriptionError,
            build_speaker,
            build_transcriber,
        )
        from .voice.loop import VoiceConfig, VoiceLoop

        try:
            transcriber = build_transcriber(cfg.stt)
            speaker = build_speaker(cfg.tts)
        except (TranscriptionError, SpeechError) as exc:
            print(f"cannot start voice: {exc}", file=sys.stderr)
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
        loop.brain.name = name  # so the loop can greet with the right name
        try:
            return loop.run()
        except CaptureError as exc:
            print(f"cannot capture audio: {exc}", file=sys.stderr)
            return 2

    if args.tools:
        registry = brain.registry
        print(f"{len(registry.names())} tools registered:\n")
        for tool_name in registry.names():
            tool = registry.get(tool_name)
            flag = "  [needs confirmation]" if tool.consequential else ""
            print(f"  {tool_name}{flag}")
            print(f"      {tool.description}")
        return 0

    # Non-interactive: -m messages, or piped stdin.
    scripted = list(args.message)
    if not scripted and not sys.stdin.isatty():
        scripted = [line for line in sys.stdin.read().splitlines() if line.strip()]

    if scripted:
        for text in scripted:
            print(f"you › {text}")
            _run_turn(brain, name, text, tracker=tracker)

        tracker.save()
        if cfg.rails.show_cost and tracker.session.calls:
            print(f"[{tracker.summary()}]")

        if args.show_transcript:
            print("\n--- transcript ---")
            for message in brain.transcript():
                if message.outputs:
                    for out in message.outputs:
                        print(f"tool[{out.name}]: {out.content}")
                elif message.calls:
                    for call in message.calls:
                        print(f"assistant->tool: {call.name}({call.args})")
                else:
                    print(f"{message.role}: {message.content}")
        return 0

    # Interactive.
    print(f"{name} is awake. Provider: {cfg.brain.provider} ({cfg.brain.model}).")
    print(f"{len(brain.registry.names())} tools available (see --tools).")

    # -- the heartbeat ------------------------------------------------------
    heartbeat = None
    if cfg.heartbeat.enabled and not args.no_heartbeat:
        if PAUSE_FILE.exists():
            print("Heartbeat: stopped (kill switch engaged — run --resume to restart).")
        else:
            hb_dict = {
                "poll_seconds": cfg.heartbeat.poll_seconds,
                "quiet_hours_enabled": cfg.heartbeat.quiet_hours_enabled,
                "quiet_hours_start": cfg.heartbeat.quiet_hours_start,
                "quiet_hours_end": cfg.heartbeat.quiet_hours_end,
                "checks": cfg.heartbeat.checks,
            }
            heartbeat = Heartbeat(hb_schedule, inbox, hb_dict, log=log.write)

            cleared = hb_schedule.clear_running_flags()
            if cleared:
                log.write(
                    source="heartbeat",
                    status="recovered",
                    detail=f"cleared {cleared} stale in-flight marker(s)",
                )

            # Catch-up on return: anything noticed while you were away is shown
            # now, rather than having been delivered once into the void.
            if cfg.heartbeat.catch_up_on_start:
                missed = heartbeat.catch_up(mark_delivered=True)
                if missed:
                    print(f"\nWhile you were away — {len(missed)} notice(s):")
                    for notice in missed:
                        flag = "!" if notice.urgent else "·"
                        print(f"  {flag} {notice.title}")
                        if notice.body:
                            for line in notice.body.splitlines():
                                print(f"      {line}")
                    print("  (clear with --dismiss)\n")

            heartbeat.start()
            print(
                f"Heartbeat: running ({len(heartbeat.checks)} checks, "
                f"quiet hours {heartbeat.quiet.describe()})."
            )

    pending = inbox.count_pending()
    if pending:
        print(f"Inbox: {pending} notice(s) waiting (see --inbox).")

    print("Type a message. /reset forgets this session, /quit exits.\n")

    while True:
        try:
            text = input("you › ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        text = text.strip()
        if not text:
            continue
        if text.lower() in EXIT_WORDS:
            break
        if text == "/reset":
            brain.reset()
            print("(session cleared)")
            continue
        if text == "/inbox":
            waiting = inbox.pending()
            if not waiting:
                print("(inbox empty)")
            for notice in waiting:
                flag = "!" if notice.urgent else "·"
                print(f"  {flag} [{notice.id}] {notice.title}")
            continue
        if text == "/dismiss":
            print(f"(dismissed {inbox.dismiss_all()} notice(s))")
            continue

        _run_turn(brain, name, text, tracker=tracker)

    if heartbeat is not None:
        heartbeat.stop()

    tracker.save()
    if cfg.rails.show_cost and tracker.session.calls:
        print(f"[{tracker.summary()}]")

    print("Goodbye.")
    return 0
