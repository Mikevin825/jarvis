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
from .memory import MemoryStore
from .paths import MEMORY_FILE
from .prompts import build_system_prompt
from .providers import ProviderError, build_provider
from .tools import build_registry

EXIT_WORDS = {"/quit", "/exit", "/q"}


def _build_brain() -> tuple:
    load_dotenv()
    cfg = load_config()

    store = MemoryStore(MEMORY_FILE)
    store.load()

    provider = build_provider(cfg.brain)
    registry = build_registry(store)

    # Memory is injected fresh each turn rather than captured once, so a fact
    # learned this turn is usable in the next, and a hand edit to the file is
    # picked up without restarting.
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


def _run_turn(brain: Brain, name: str, text: str, verbose_tools: bool = True) -> None:
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
                    status = "ok" if event.ok else "FAILED"
                    print(f"  · {event.name}{_fmt_args(event.args)} → {status}")
                    if not event.ok:
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
    args = parser.parse_args(argv)

    try:
        cfg, brain, store = _build_brain()
    except ConfigError as exc:
        print(f"configuration problem: {exc}", file=sys.stderr)
        return 2
    except ProviderError as exc:
        print(f"cannot start: {exc}", file=sys.stderr)
        return 2

    name = cfg.assistant.name

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
            _run_turn(brain, name, text)
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
    print(
        f"{len(brain.registry.names())} tools available "
        f"({'/tools' if False else 'see --tools'})."
    )
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

        _run_turn(brain, name, text)

    print("Goodbye.")
    return 0
