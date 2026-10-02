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
from .prompts import build_system_prompt
from .providers import ProviderError, build_provider
from .tools import build_registry

EXIT_WORDS = {"/quit", "/exit", "/q"}


def _build_brain() -> tuple:
    load_dotenv()
    cfg = load_config()
    provider = build_provider(cfg.brain)
    registry = build_registry()
    return cfg, Brain(provider, build_system_prompt(cfg.assistant), registry)


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
