"""Personality: a living file, and the mechanism that stops it drifting.

Two problems this solves, both real and both measured in practice:

**1. Personality trapped in code is personality nobody tunes.** The voice lives
in `personality.md`, plain prose, re-read on every turn. Edit it, save it, and
the very next reply uses it — no restart, no redeploy.

**2. Voice drifts toward generic-assistant mode over a long conversation.** This
is not a bug in the prompt; it is how attention works. As history grows, the
assistant's *own prior outputs* become the strongest behavioural signal and
progressively outweigh the personality block sitting at the top of the context.
Once one reply slips into "Great question!", that reply becomes the reference
point for the next, and the slide compounds.

The fix is **positional, not motivational**. A short voice cue is appended to
the last user message — *after* every prior assistant turn, in the position the
model attends to most strongly — without ever being stored in history. The cue
carries concrete examples rather than adjectives, because a model imitates
examples and merely nods at adjectives.

The cue is built from this file, so the two can never disagree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERSONALITY_FILE = ROOT / "personality.md"

# How many example lines to carry into the per-turn cue. Enough to anchor the
# voice, few enough to stay cheap and not swamp the actual message.
MAX_SOUND_LIKE = 4
MAX_BANNED = 8


@dataclass
class Personality:
    """The assistant's voice, loaded from a file."""

    text: str = ""
    sound_like: list[str] = field(default_factory=list)
    never_like: list[str] = field(default_factory=list)
    loaded_from: Path | None = None
    _stamp: float | None = None

    @property
    def present(self) -> bool:
        return bool(self.text.strip())

    def render(self) -> str:
        """The personality block for the system prompt."""
        return self.text.strip()

    def voice_cue(self) -> str:
        """The per-turn reminder appended after the last user message.

        Returns "" when there is no personality to reinforce, so a bare install
        does not carry a cue that refers to nothing.
        """
        if not self.present:
            return ""

        lines = ["[voice — stay in character; this overrides any drift toward "
                 "generic assistant phrasing]"]

        if self.sound_like:
            lines.append("Sound like this:")
            for example in self.sound_like[:MAX_SOUND_LIKE]:
                lines.append(f"  {example}")

        if self.never_like:
            banned = "; ".join(f'"{b}"' for b in self.never_like[:MAX_BANNED])
            lines.append(f"Never open with: {banned}.")

        lines.append(
            "Be brief and spoken. Lead with the answer. Don't narrate what you're "
            "about to do."
        )
        return "\n".join(lines)


def _bullets_under(text: str, heading: str) -> list[str]:
    """Pull the bullet lines from the section beginning at `heading`.

    Deliberately simple: personality.md is a file a human edits, so the parser
    is forgiving. A missing or renamed section yields an empty list rather than
    an error — a typo in the prose must never stop the assistant starting.
    """
    lines = text.splitlines()
    collected: list[str] = []
    inside = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            # A new heading of the same or higher level ends the section.
            if inside and len(stripped) - len(stripped.lstrip("#")) <= heading.count("#"):
                break
            if heading.lower() in stripped.lower():
                inside = True
            continue
        if not inside:
            continue
        if stripped.startswith(("-", "*", "•")):
            value = stripped.lstrip("-*• ").strip()
            value = value.strip('"“”')
            if value:
                collected.append(value)

    return collected


def load_personality(path: Path | None = None, *, force: bool = False) -> Personality:
    """Read the personality file, re-reading it when it changes on disk.

    Caching is keyed on mtime, so editing the file takes effect immediately
    without restarting — which is the whole point of keeping it in a file.
    """
    target = path or PERSONALITY_FILE
    if not target.exists():
        return Personality()

    try:
        stamp = target.stat().st_mtime
    except OSError:
        return Personality()

    cached = _CACHE.get(str(target))
    if cached is not None and not force and cached._stamp == stamp:
        return cached

    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return Personality()

    personality = Personality(
        text=text,
        sound_like=_bullets_under(text, "### Sound like this"),
        never_like=_bullets_under(text, "### Never sound like this"),
        loaded_from=target,
        _stamp=stamp,
    )
    _CACHE[str(target)] = personality
    return personality


_CACHE: dict[str, Personality] = {}
