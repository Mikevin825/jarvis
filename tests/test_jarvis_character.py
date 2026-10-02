"""The personality must actually be the MCU JARVIS register.

These tests pin the character down. They are not style preferences — if the
personality file drifts, the assistant stops sounding like itself, and that is
exactly the kind of regression that is easy to miss by eye.
"""

from __future__ import annotations

from jarvis.personality import load_personality


def real_personality():
    """The shipped personality.md, not a fixture."""
    from jarvis.personality import PERSONALITY_FILE

    return load_personality(PERSONALITY_FILE, force=True)


def test_personality_file_exists_and_loads():
    p = real_personality()
    assert p.present, "personality.md is missing — the assistant has no voice"
    assert len(p.sound_like) >= 5, "too few voice examples to anchor the model"
    assert len(p.never_like) >= 5, "too few banned phrasings"


def test_it_specifies_the_form_of_address():
    """'Sir' is the defining register of the MCU character."""
    text = real_personality().text
    assert "sir" in text.lower()
    # And it should be a deliberate instruction, not incidental.
    assert '"Sir."' in text or 'Address Mike as "sir"' in text


def test_it_is_modelled_on_the_mcu_character():
    text = real_personality().text.lower()
    assert "mcu" in text or "valet" in text or "butler" in text


def test_it_forbids_obsequiousness():
    """The failure mode of a butler persona is servility, not coldness."""
    text = real_personality().text.lower()
    assert "obsequious" in text or "servil" in text
    assert "never obsequious" in text or "not obsequious" in text


def test_it_keeps_the_counterweights():
    """Snark without guardrails produces a roast bot, which is worse."""
    text = real_personality().text.lower()
    assert "warmth" in text or "loyal" in text
    assert "not cold" in text or "never cold" in text


def test_it_still_carries_the_safety_boundaries():
    """Character must not have displaced the rules."""
    text = real_personality().text.lower()
    assert "ask before" in text
    assert "sends, spends, deletes" in text
    assert "data" in text and "instruction" in text


def test_voice_examples_are_valet_register():
    p = real_personality()
    joined = " ".join(p.sound_like).lower()
    assert "sir" in joined, "the examples should demonstrate the register"


def test_banned_phrasings_include_the_worst_offenders():
    p = real_personality()
    banned = " ".join(p.never_like).lower()
    for phrase in ("great question", "happy to help", "as an ai language model"):
        assert phrase in banned, f"{phrase!r} should be explicitly banned"


def test_the_cue_carries_the_character_into_every_turn():
    cue = real_personality().voice_cue()
    assert "sir" in cue.lower()
    assert "Great question!" in cue


def test_the_cue_still_asks_for_brevity():
    cue = real_personality().voice_cue()
    assert "brief" in cue.lower() or "Lead with the answer" in cue
