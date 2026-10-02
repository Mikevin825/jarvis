"""Push-to-talk bindings: single keys and combinations.

The default changed from space to F9 because space fires on every keystroke once
the assistant runs outside a terminal. These tests pin that down.
"""

from __future__ import annotations

import pytest

from jarvis.voice.keys import KeyCombo


def test_single_key_matches_only_itself():
    combo = KeyCombo("f9")
    assert combo.is_valid
    assert combo.matches("f9", set())
    assert not combo.matches("f8", set())
    assert not combo.matches("space", set())


def test_single_key_does_not_fire_with_a_modifier_held():
    """Otherwise Ctrl+F9 would trigger dictation mid-shortcut."""
    combo = KeyCombo("f9")
    assert not combo.matches("f9", {"ctrl"})


def test_combination_requires_every_modifier():
    combo = KeyCombo("<ctrl>+<alt>+j")
    assert combo.matches("j", {"ctrl", "alt"})
    assert not combo.matches("j", {"ctrl"})
    assert not combo.matches("j", {"alt"})
    assert not combo.matches("j", set())


def test_combination_does_not_fire_with_an_extra_modifier():
    """Exact matching stops it colliding with other shortcuts."""
    combo = KeyCombo("<ctrl>+<alt>+j")
    assert not combo.matches("j", {"ctrl", "alt", "shift"})


def test_modifier_order_does_not_matter():
    a = KeyCombo("<ctrl>+<alt>+j")
    b = KeyCombo("<alt>+<ctrl>+j")
    assert a.matches("j", {"ctrl", "alt"})
    assert b.matches("j", {"ctrl", "alt"})


@pytest.mark.parametrize("alias", ["ctrl", "control"])
def test_modifier_aliases(alias):
    assert KeyCombo(f"<{alias}>+j").matches("j", {"ctrl"})


@pytest.mark.parametrize("alias", ["super", "cmd", "win", "meta"])
def test_super_aliases(alias):
    assert KeyCombo(f"<{alias}>+j").matches("j", {"super"})


def test_shifted_function_key():
    combo = KeyCombo("<shift>+f10")
    assert combo.matches("f10", {"shift"})
    assert not combo.matches("f10", set())


@pytest.mark.parametrize("bad", ["", "   ", "<ctrl>", "<alt>+<shift>"])
def test_bare_modifiers_are_not_usable_bindings(bad):
    """A lone modifier would trigger merely reaching for a shortcut."""
    assert KeyCombo(bad).is_valid is False


def test_description_is_human_readable():
    assert KeyCombo("f9").describe() == "F9"
    assert KeyCombo("<ctrl>+<alt>+j").describe() == "Ctrl+Alt+J"
    assert KeyCombo("space").describe() == "SPACE"


def test_space_still_works_if_someone_insists():
    assert KeyCombo("space").matches("space", set())


def test_default_binding_is_not_space():
    """The regression that caused phantom recordings when backgrounded."""
    from jarvis.voice.loop import VoiceConfig

    assert VoiceConfig().ptt_key != "space"
