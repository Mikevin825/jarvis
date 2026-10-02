"""Push-to-talk key handling, including modifier combinations.

Push-to-talk started as a single key (space). That is fine in a terminal, where
you are not typing prose into the assistant, but as a background desktop
assistant space is the single most-typed key on the keyboard — it fires on every
keystroke. So the default is now a function key, and combinations like
`<ctrl>+<alt>+j` are supported for people who want something they can press
without leaving the home row.

A combo is written the way `pynput` writes hotkeys: `<ctrl>+<alt>+j`, `f9`,
`<shift>+<super>+space`. Matching is done here rather than with `GlobalHotKeys`
because push-to-talk needs press *and* release, and it needs to know the exact
set of held modifiers at the moment the trigger key goes down.
"""

from __future__ import annotations

MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
    "super": "super",
    "cmd": "super",
    "win": "super",
    "meta": "super",
}


class KeyCombo:
    """A parsed push-to-talk binding: a trigger key plus required modifiers."""

    def __init__(self, spec: str) -> None:
        self.spec = (spec or "").strip().lower()
        self.modifiers: frozenset[str] = frozenset()
        self.key: str = ""
        self._parse(self.spec)

    def _parse(self, spec: str) -> None:
        if not spec:
            self.key = ""
            return

        parts = [p for p in spec.split("+") if p.strip()]
        mods: set[str] = set()
        key = ""

        for part in parts:
            token = part.strip().strip("<>").lower()
            if token in MODIFIER_ALIASES:
                mods.add(MODIFIER_ALIASES[token])
            else:
                # The last non-modifier token is the trigger key.
                key = token

        # A bare modifier is not a usable binding — you would trigger it by
        # merely reaching for a shortcut.
        if not key and mods:
            key = ""
            mods = set()

        self.modifiers = frozenset(mods)
        self.key = key

    @property
    def is_valid(self) -> bool:
        return bool(self.key)

    @property
    def is_single_key(self) -> bool:
        return self.is_valid and not self.modifiers

    def matches(self, key_name: str, held_modifiers: set[str]) -> bool:
        """True when this event is the trigger key with exactly these modifiers.

        Requiring an exact match means `<ctrl>+j` does not fire when the user
        presses `<ctrl>+<alt>+j` for something else.
        """
        if not self.is_valid:
            return False
        if key_name != self.key:
            return False
        return set(held_modifiers) == set(self.modifiers)

    def describe(self) -> str:
        if not self.is_valid:
            return "(unset)"
        if not self.modifiers:
            return self.key.upper()
        order = ["ctrl", "alt", "shift", "super"]
        mods = [m for m in order if m in self.modifiers]
        return "+".join(m.capitalize() for m in mods + [self.key.upper()])


def key_name_from_event(key) -> str:
    """A stable lowercase name for a pressed key, across pynput's types."""
    try:
        from pynput import keyboard
    except ImportError:  # pragma: no cover
        return ""

    if isinstance(key, keyboard.Key):
        return key.name.lower()
    char = getattr(key, "char", None)
    return char.lower() if char else ""


def modifier_from_key(key) -> str | None:
    """Which modifier (if any) a key event represents."""
    try:
        from pynput import keyboard
    except ImportError:  # pragma: no cover
        return None

    if not isinstance(key, keyboard.Key):
        return None

    name = key.name.lower()
    if name in ("ctrl", "ctrl_l", "ctrl_r"):
        return "ctrl"
    if name in ("alt", "alt_l", "alt_r", "alt_gr"):
        return "alt"
    if name in ("shift", "shift_l", "shift_r"):
        return "shift"
    if name in ("cmd", "cmd_l", "cmd_r"):
        return "super"
    return None
