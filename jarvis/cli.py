"""Text entry point.

The plain-text interface. It stays alive for the life of the project: it is how
every future change gets debugged without talking to the computer, and it is the
graceful fallback when audio misbehaves.

Reads from the terminal when interactive, or from stdin when piped, so the same
loop can be driven by a script or a test.
"""

from __future__ import annotations

import argparse
import os
import select
import sys
import threading
from pathlib import Path

from .brain import Brain, Chunk, ToolRun
from .config import ConfigError, load_config, load_dotenv
from .cost import CostTracker
from .galaxy_bridge import GalaxyBridge
from .gate import CliGate, DenyAllGate, NoHumanGate
from .memory import MemoryStore
from .personality import load_personality
from .paths import (
    AUDIT_FILE,
    COST_FILE,
    INBOX_FILE,
    MEMORY_FILE,
    PAUSE_FILE,
    SCHEDULE_FILE,
)
from .prompts import build_self_knowledge, build_system_prompt
from .providers import ProviderError, build_provider
from .session import SessionStore
from .tools import build_registry

EXIT_WORDS = {"/quit", "/exit", "/q"}

# Lines typed while a reply is being spoken aloud are held here rather than
# discarded, so pressing Enter mid-speech and then typing a message still works.
_input_buffer: list[str] = []


def _read_input(prompt: str) -> str:
    """`input()`, but serving anything buffered from a speech interlude first."""
    if _input_buffer:
        return _input_buffer.pop(0)
    return input(prompt)


def _speak_reply(text: str, speaker, *, interactive: bool = True) -> None:
    """Read a reply aloud, and let the user cut it short.

    A long reply can easily outlast the user's patience, so Enter stops the
    speech. Anything else typed while it speaks is buffered and becomes the
    next message — losing the user's words to a running speaker would be a
    worse outcome than making them wait a moment.

    When input is piped there is nobody to press Enter, and readline() at EOF
    returns an empty line, which must not be mistaken for a skip — so the
    speech simply plays out.

    TTS failure is not fatal: the text is still on screen, and a broken voice
    must not take down a working text session.
    """
    body = text.strip()
    if not body:
        return

    done = threading.Event()

    def _run() -> None:
        try:
            speaker.speak(body)
        except Exception:  # noqa: BLE001 - a voice problem must not kill the turn
            pass
        finally:
            done.set()

    threading.Thread(target=_run, daemon=True).start()

    if not interactive:
        done.wait()
        return

    print("  (speaking — Enter to skip)", end="", flush=True)
    while not done.is_set():
        ready, _, _ = select.select([sys.stdin], [], [], 0.2)
        if not ready:
            continue
        line = sys.stdin.readline()
        if line == "":
            # EOF, not a keypress — let the speech finish rather than cutting
            # it short on the user's behalf.
            done.wait()
            break
        if line.strip() == "":
            speaker.stop()
            print("  (stopped)")
            return
        _input_buffer.append(line)
        print("  (queued while speaking)")
    print()



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
        provider=build_provider(cfg.brain),
    )

    # The gate is attached to the registry, so it covers every consequential
    # action regardless of where the turn came from.
    registry.gate = gate if gate is not None else DenyAllGate()

    personality = load_personality()

    # Load core knowledge (curated, always-loaded facts)
    core_knowledge_path = Path(__file__).resolve().parent.parent / "state" / "core-knowledge.md"
    core_knowledge = ""
    if core_knowledge_path.exists():
        try:
            core_knowledge = core_knowledge_path.read_text(encoding="utf-8")
        except OSError:
            core_knowledge = ""

    tool_names = registry.names()

    def _build_prompt(facts: str = "", turn_count: int = 0) -> str:
        sp = build_system_prompt(
            cfg.assistant, facts, personality=personality,
            core_knowledge=core_knowledge,
            self_knowledge=build_self_knowledge(tool_names),
            turn_count=turn_count,
        )
        return sp.stable

    def _build_dynamic(turn_count: int = 0) -> str:
        sp = build_system_prompt(
            cfg.assistant, personality=personality,
            core_knowledge=core_knowledge,
            self_knowledge=build_self_knowledge(tool_names),
            turn_count=turn_count,
        )
        return sp.dynamic

    brain = Brain(
        provider,
        _build_prompt(turn_count=0),
        registry,
        memory_selector=lambda turn: store.render(store.relevant(turn)),
        prompt_builder=_build_prompt,
        # Re-read every turn, so editing personality.md takes effect on the very
        # next reply without a restart.
        voice_cue=lambda: load_personality().voice_cue(),
        # The bridge to the galaxy. Writes state and agent events to disk, so
        # the constellation lights up the right sub-agent when a tool runs.
        galaxy=GalaxyBridge(),
    )
    brain.set_dynamic_block(_build_dynamic(turn_count=0))

    # Session persistence — recover last session on startup
    session_store = SessionStore(Path("state/session.json"))
    recovered = session_store.load()
    if recovered:
        brain.history.extend(recovered)

    return cfg, brain, store, session_store, provider


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
    speaker=None,
    speak: bool = False,
) -> None:
    """Run one turn, streaming the reply to the terminal.

    Tool activity is shown on its own line so it is always visible what the
    assistant actually did, not just what it said. The name prefix is printed
    only once real text arrives, so a failure before any output never leaves a
    dangling prompt on screen.

    With `speak`, the reply is also read aloud once it is complete — the text
    is collected here rather than spoken chunk by chunk, so the voice gets a
    whole answer instead of a staccato one.
    """
    spoke = False
    parts: list[str] = []
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
                parts.append(event.text)
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

    if speak and speaker is not None:
        _speak_reply("".join(parts), speaker, interactive=sys.stdin.isatty())


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
        help="start the push-to-talk voice interface (this is the default)",
    )
    parser.add_argument(
        "--text",
        action="store_true",
        help="start the typed text interface instead of voice",
    )
    parser.add_argument(
        "--speak",
        action="store_true",
        help=(
            "typed text in, spoken replies out: type a message, read the answer "
            "and hear it read aloud (implies --text)"
        ),
    )
    parser.add_argument(
        "--wake",
        action="store_true",
        help=(
            "listen for the wake word instead of holding a key: say the wake "
            "word, then speak your request (implies voice mode)"
        ),
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
        "--status-report",
        dest="status_report",
        action="store_true",
        help="read the configured website and YouTube channel, print a status report, exit",
    )
    parser.add_argument(
        "--analytics",
        dest="analytics",
        action="store_true",
        help="print trends over time — views growth, upload rate, site uptime — and exit",
    )
    parser.add_argument(
        "--daily",
        dest="daily",
        action="store_true",
        help=(
            "print traffic per day — views on each day, busiest day, and each "
            "video's daily rate — and exit"
        ),
    )
    parser.add_argument(
        "--graph-sheet",
        dest="graph_sheet",
        action="store_true",
        help="write an HTML graph sheet of every trend to reports/ and exit",
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
    parser.add_argument(
        "--personality",
        action="store_true",
        help="show the personality file and the per-turn voice cue",
    )
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="open the desktop panel (a window, not a terminal)",
    )
    parser.add_argument(
        "--board",
        action="store_true",
        help="open the board meetings panel",
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
        cfg, brain, store, session_store, provider = _build_brain(gate=gate)
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

    if args.personality:
        from .personality import PERSONALITY_FILE, load_personality

        p = load_personality()
        print(f"Personality: {PERSONALITY_FILE}")
        print(f"  loaded:      {p.present}")
        print(f"  size:        {len(p.text):,} chars")
        print(f"  examples:    {len(p.sound_like)} sound-like, {len(p.never_like)} never-like")
        print(f"  re-read:     every turn (edit the file and it takes effect immediately)")
        print("\n--- the per-turn voice cue (appended after your message) ---")
        print(p.voice_cue() or "(none — no personality file found)")
        print("\n--- the file ---")
        print(p.render() or "(missing)")
        return 0

    if args.desktop:
        # Hand off to the desktop entry point, which owns the window and its
        # own gate. Importing here keeps tkinter out of the terminal path.
        from .desktop.__main__ import main as desktop_main

        return desktop_main()

    if args.board:
        from .desktop.board_panel import BoardPanel

        panel = BoardPanel()
        panel.run()
        return 0

    # -- status report on the business's online presence ---------------------
    if args.status_report:
        from .presence import generate_status_report

        if not cfg.presence.all_websites and not cfg.presence.all_channels:
            print(
                "Nothing is configured to report on.\n"
                "Add `presence.websites` and/or `presence.youtube_channels` "
                "to config.yaml."
            )
            return 2
        print(
            generate_status_report(
                websites=cfg.presence.all_websites,
                channels=cfg.presence.all_channels,
            )
        )
        return 0

    # -- traffic per day -------------------------------------------------------
    if args.daily:
        from .presence import render_daily

        print(render_daily())
        return 0

    # -- analytics: trends over time ------------------------------------------
    if args.analytics:
        from .presence import render_analytics

        print(render_analytics())
        return 0

    # -- graph sheet: every trend as a chart ----------------------------------
    if args.graph_sheet:
        from .presence.tools import presence_graph_sheet

        print(presence_graph_sheet())
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
            build_speaker_with_fallback,
            build_transcriber,
        )
        from .voice.loop import VoiceConfig, VoiceLoop

        try:
            transcriber = build_transcriber(cfg.stt)
            speaker = build_speaker_with_fallback(cfg.tts)
        except (TranscriptionError, SpeechError) as exc:
            print(f"cannot start voice: {exc}", file=sys.stderr)
            return 2

        if speaker.provider != cfg.tts.provider:
            # Same rule as speak mode: a substitution is announced, not hidden.
            print(f"Voice output: using '{speaker.provider}' instead of '{cfg.tts.provider}'.")

        bridge = GalaxyBridge()
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
            galaxy_bridge=bridge,
        )
        path = Path(args.voice_file)
        if not path.exists():
            print(f"no such file: {path}", file=sys.stderr)
            return 2
        loop.handle_recording(path, consume=False)  # keep the fixture
        return 0

    # -- the voice interface (default unless --text or --speak is given) ------
    # Voice is the default input mode. --text and --speak both opt into the
    # typed interface; --speak additionally reads every reply aloud.
    # -m messages and piped stdin still work as non-interactive input.
    if not args.text and not args.speak and not args.message and sys.stdin.isatty():
        from .voice import (
            CaptureError,
            SpeechError,
            TranscriptionError,
            build_speaker_with_fallback,
            build_transcriber,
        )
        from .voice.loop import VoiceConfig, VoiceLoop

        try:
            transcriber = build_transcriber(cfg.stt)
            speaker = build_speaker_with_fallback(cfg.tts)
        except (TranscriptionError, SpeechError) as exc:
            print(f"cannot start voice: {exc}", file=sys.stderr)
            return 2

        if speaker.provider != cfg.tts.provider:
            # Same rule as speak mode: a substitution is announced, not hidden.
            print(f"Voice output: using '{speaker.provider}' instead of '{cfg.tts.provider}'.")

        bridge = GalaxyBridge()
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
            galaxy_bridge=bridge,
        )
        loop.brain.name = name  # so the loop can greet with the right name

        # -- wake word mode: no key to hold, just say his name ---------------
        # The listener is a producer; the loop still owns the turn.
        if args.wake:
            from .voice.wake import (
                OPENWAKEWORD_KEYWORDS,
                OpenWakeWordDetector,
                PorcupineDetector,
                WakeError,
                WakeListener,
            )

            if not cfg.voice.wake_word:
                print(
                    "wake_word is empty in config.yaml — set it to a keyword\n"
                    "  (jarvis is built in) or drop --wake to use push-to-talk.",
                    file=sys.stderr,
                )
                return 2

            # Porcupine when a key is configured, openWakeWord otherwise. The
            # latter needs no account and no key, which is the whole reason it
            # is here: Picovoice's free tier asks for a company email.
            access_key = os.environ.get("PORCUPINE_ACCESS_KEY", "").strip()
            try:
                if access_key:
                    detector = PorcupineDetector(
                        access_key=access_key,
                        keyword=cfg.voice.wake_word,
                        sensitivity=cfg.voice.wake_sensitivity,
                    )
                    engine = "porcupine"
                else:
                    # The two engines name the same word differently.
                    keyword = OPENWAKEWORD_KEYWORDS.get(
                        cfg.voice.wake_word, cfg.voice.wake_word
                    )
                    detector = OpenWakeWordDetector(
                        keyword=keyword,
                        threshold=cfg.voice.wake_sensitivity,
                    )
                    engine = "openwakeword"
            except WakeError as exc:
                print(f"cannot start wake mode: {exc}", file=sys.stderr)
                return 2

            listener = WakeListener(detector, submit=loop.submit_recording)
            listener.start()
            print(
                f"{name} is listening for \"{cfg.voice.wake_word}\" ({engine}). "
                "Say it, then speak your request."
            )
            try:
                return loop.run()
            except CaptureError as exc:
                print(f"cannot capture audio: {exc}", file=sys.stderr)
                return 2
            finally:
                listener.stop()
                detector.close()

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

    # Speak mode applies here too: `jarvis --speak -m "hi"` should talk back.
    _scripted_speaker = None
    _scripted_speaking = False
    if scripted and args.speak:
        from .voice import SpeechError, build_speaker_with_fallback

        def _announce_switch(provider: str) -> None:
            print(f"  (voice: switched to '{provider}')")

        try:
            _scripted_speaker = build_speaker_with_fallback(
                cfg.tts, on_switch=_announce_switch
            )
            _scripted_speaking = True
        except SpeechError as exc:
            print(f"Speak mode unavailable, continuing in text only: {exc}")

    if scripted:
        for text in scripted:
            print(f"you › {text}")
            _run_turn(
                brain, name, text, tracker=tracker,
                speaker=_scripted_speaker, speak=_scripted_speaking,
            )

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

    # -- the speak mode: typed in, spoken out --------------------------------
    # The speaker is built lazily and only in this mode, so a machine with no
    # TTS configured can still run the plain text interface.
    speaker = None
    speaking = False
    if args.speak:
        from .voice import SpeechError, build_speaker_with_fallback

        def _announce_switch(provider: str) -> None:
            print(f"  (voice: switched to '{provider}')")

        try:
            speaker = build_speaker_with_fallback(cfg.tts, on_switch=_announce_switch)
        except SpeechError as exc:
            print(f"Speak mode unavailable, continuing in text only: {exc}")
        else:
            speaking = True
            if speaker.provider != cfg.tts.provider:
                # Never substitute silently: the user picked a voice, and
                # silently hearing a different one reads as a bug.
                print(
                    f"Speak mode: '{cfg.tts.provider}' could not be used, "
                    f"so replies will be read in '{speaker.provider}' instead."
                )
            print(
                "Speak mode: every reply is read aloud. "
                "Press Enter during speech to skip; /speak off to silence."
            )

    # -- voice verification ---------------------------------------------------
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

            # Start reminder scheduler so notifications work immediately
            from .tools.reminders import start_scheduler
            start_scheduler()

    # Start reminder scheduler for non-interactive mode too
    if not cfg.heartbeat.enabled or args.no_heartbeat:
        from .tools.reminders import start_scheduler
        start_scheduler()

    pending = inbox.count_pending()
    if pending:
        print(f"Inbox: {pending} notice(s) waiting (see --inbox).")

    print("Type a message. /reset forgets this session, /quit exits.\n")

    while True:
        try:
            text = _read_input("you › ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        text = text.strip()
        if not text:
            continue
        if text.lower() in EXIT_WORDS:
            # Run automatic memory extractor before exiting
            try:
                from .memory.extractor import extract_memories
                transcript = [
                    {"role": m.role, "content": m.content or ""}
                    for m in brain.history
                    if m.content
                ]
                memories = extract_memories(transcript, store, provider, max_memories=5)
                for mem in memories:
                    store.add(mem.fact, type=mem.type, hook=mem.hook)
                if memories:
                    print(f"(Saved {len(memories)} memories)")
            except Exception:
                pass  # Extractor must never block exit
            break
        if text == "/reset":
            brain.reset()
            print("(session cleared)")
            continue
        if text == "/speak":
            speaking = not speaking
            if speaking and speaker is None:
                print("(no speaker available — speak mode failed to start)")
                speaking = False
            else:
                print(f"(replies will {'now be' if speaking else 'no longer be'} spoken aloud)")
            continue
        if text.startswith("/speak "):
            choice = text.split(None, 1)[1].strip().lower()
            if choice in ("on", "true", "yes"):
                speaking = True
            elif choice in ("off", "false", "no"):
                speaking = False
            else:
                print("(use /speak on or /speak off)")
                continue
            if speaking and speaker is None:
                print("(no speaker available — speak mode failed to start)")
                speaking = False
            else:
                print(f"(replies will {'now be' if speaking else 'no longer be'} spoken aloud)")
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

        _run_turn(brain, name, text, tracker=tracker, speaker=speaker, speak=speaking)
        session_store.save(brain.history)

    if heartbeat is not None:
        heartbeat.stop()

    tracker.save()
    if cfg.rails.show_cost and tracker.session.calls:
        print(f"[{tracker.summary()}]")

    print("Goodbye.")
    return 0
