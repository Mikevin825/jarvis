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

from .brain import Brain
from .config import ConfigError, load_config, load_dotenv
from .prompts import build_system_prompt
from .providers import ProviderError, build_provider

EXIT_WORDS = {"/quit", "/exit", "/q"}


def _build_brain():
    load_dotenv()
    cfg = load_config()
    provider = build_provider(cfg.brain)
    return cfg, Brain(provider, build_system_prompt(cfg.assistant))


def _run_turn(brain: Brain, name: str, text: str) -> None:
    """Run one turn, streaming the reply to the terminal.

    The name prefix is only printed once the first chunk arrives, so a failure
    before any output never leaves a dangling prompt on screen.
    """
    spoke = False
    try:
        for chunk in brain.ask(text):
            if not spoke:
                print(f"{name} › ", end="", flush=True)
                spoke = True
            print(chunk, end="", flush=True)
    except ProviderError as exc:
        # A network call failed. Shrug it off, say so clearly, keep the session.
        print(f"[brain unavailable] {exc}")
        return
    if spoke:
        print()
    else:
        # The model returned an empty turn; say so rather than showing silence.
        print(f"{name} › (empty reply)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jarvis", description="Talk to JARVIS in plain text (Tier 1)."
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
    args = parser.parse_args(argv)

    try:
        cfg, brain = _build_brain()
    except ConfigError as exc:
        print(f"configuration problem: {exc}", file=sys.stderr)
        return 2
    except ProviderError as exc:
        print(f"cannot start: {exc}", file=sys.stderr)
        return 2

    name = cfg.assistant.name

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
                print(f"{message.role}: {message.content}")
        return 0

    # Interactive.
    print(f"{name} is awake. Provider: {cfg.brain.provider} ({cfg.brain.model}).")
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
