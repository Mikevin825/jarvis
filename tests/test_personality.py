"""Personality: a living file, and the cue that stops the voice drifting."""

from __future__ import annotations

import os
import time

from jarvis.brain import Brain
from jarvis.personality import Personality, load_personality
from jarvis.prompts import build_system_prompt
from jarvis.providers import TextDelta, TurnEnd


SAMPLE = """\
# Test personality

## How I sound

### Sound like this

- "It's 27 degrees. Clear."
- "Done. Saved."
- "I don't know."

### Never sound like this

- "Great question!"
- "I'd be happy to help."

## How I behave

- Lead with the answer.
"""


def write_personality(tmp_path, text=SAMPLE):
    path = tmp_path / "personality.md"
    path.write_text(text)
    return path


# -- loading ----------------------------------------------------------------


def test_missing_file_is_not_an_error(tmp_path):
    p = load_personality(tmp_path / "nope.md")
    assert p.present is False
    assert p.voice_cue() == ""


def test_examples_are_parsed_out_of_the_file(tmp_path):
    p = load_personality(write_personality(tmp_path), force=True)
    assert p.present
    assert "It's 27 degrees. Clear." in p.sound_like
    assert "Great question!" in p.never_like


def test_quotes_are_stripped_from_examples(tmp_path):
    p = load_personality(write_personality(tmp_path), force=True)
    for example in p.sound_like + p.never_like:
        assert not example.startswith('"')
        assert not example.endswith('"')


def test_editing_the_file_takes_effect_without_restart(tmp_path):
    """The whole point of keeping the personality in a file."""
    path = write_personality(tmp_path)
    first = load_personality(path, force=True)
    assert "Done. Saved." in first.sound_like

    time.sleep(0.01)
    path.write_text(SAMPLE.replace("Done. Saved.", "Finished. Filed."))
    os.utime(path, (time.time() + 1, time.time() + 1))

    second = load_personality(path)
    assert "Finished. Filed." in second.sound_like


def test_a_malformed_file_does_not_break_startup(tmp_path):
    path = tmp_path / "personality.md"
    path.write_text("just some prose with no sections at all")
    p = load_personality(path, force=True)
    assert p.present
    assert p.sound_like == []
    assert p.never_like == []


# -- the cue ----------------------------------------------------------------


def test_cue_carries_concrete_examples(tmp_path):
    p = load_personality(write_personality(tmp_path), force=True)
    cue = p.voice_cue()
    assert "It's 27 degrees. Clear." in cue


def test_cue_carries_the_banned_openers(tmp_path):
    p = load_personality(write_personality(tmp_path), force=True)
    cue = p.voice_cue()
    assert "Great question!" in cue
    assert "Never open with" in cue


def test_cue_has_positive_direction_not_just_bans(tmp_path):
    """A pure ban-list produces blandly compliant replies."""
    p = load_personality(write_personality(tmp_path), force=True)
    cue = p.voice_cue()
    assert "Sound like this" in cue
    assert "Lead with the answer" in cue or "brief" in cue.lower()


def test_cue_is_empty_without_a_personality():
    assert Personality().voice_cue() == ""


# -- the cue's position, and that it is not stored --------------------------


def _spy_brain(tmp_path):
    seen = {}

    class Spy:
        supports_tools = True

        def stream(self, system, messages, tools=None):
            seen["messages"] = list(messages)
            seen["system"] = system
            yield TextDelta("ok")
            yield TurnEnd(text="ok", raw=None, calls=[])

    p = load_personality(write_personality(tmp_path), force=True)
    brain = Brain(Spy(), "SYS", None, voice_cue=lambda: p.voice_cue())
    return brain, seen


def test_cue_is_appended_to_the_last_user_message(tmp_path):
    brain, seen = _spy_brain(tmp_path)
    list(brain.ask("what is the weather"))

    last = seen["messages"][-1]
    assert last.role == "user"
    assert last.content.startswith("what is the weather")
    assert "[voice —" in last.content, "the cue must ride on the user's turn"


def test_cue_comes_after_prior_assistant_turns(tmp_path):
    """Position is the mechanism: it must sit after what the model imitates."""
    brain, seen = _spy_brain(tmp_path)
    list(brain.ask("first"))
    list(brain.ask("second"))

    roles = [m.role for m in seen["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert "[voice —" in seen["messages"][-1].content
    assert "[voice —" not in seen["messages"][1].content


def test_cue_is_never_written_to_history(tmp_path):
    """Storing it would make it another assistant turn to imitate."""
    brain, _seen = _spy_brain(tmp_path)
    list(brain.ask("hello"))
    for message in brain.history:
        assert "[voice —" not in (message.content or "")


def test_history_does_not_accumulate_cues_over_many_turns(tmp_path):
    brain, _seen = _spy_brain(tmp_path)
    for i in range(6):
        list(brain.ask(f"turn {i}"))
    joined = " ".join(m.content or "" for m in brain.history)
    assert joined.count("[voice —") == 0


def test_a_broken_cue_does_not_stop_the_reply():
    def explode():
        raise RuntimeError("cue is broken")

    class Spy:
        supports_tools = True

        def stream(self, system, messages, tools=None):
            yield TextDelta("still works")
            yield TurnEnd(text="still works", raw=None, calls=[])

    brain = Brain(Spy(), "SYS", None, voice_cue=explode)
    events = list(brain.ask("hi"))
    assert any(getattr(e, "text", "") == "still works" for e in events)


# -- the system prompt ------------------------------------------------------


def test_system_prompt_carries_the_personality(tmp_path):
    from jarvis.config import AssistantConfig

    assistant = AssistantConfig(name="JARVIS", purpose="help", tone="crisp")
    p = load_personality(write_personality(tmp_path), force=True)
    prompt = build_system_prompt(assistant, personality=p)
    assert "You are JARVIS" in prompt
    assert "Sound like this" in prompt


def test_system_prompt_falls_back_to_tone_without_a_file(tmp_path):
    from jarvis.config import AssistantConfig

    assistant = AssistantConfig(name="JARVIS", purpose="help", tone="crisp")
    prompt = build_system_prompt(assistant, personality=Personality())
    assert "crisp" in prompt
    assert "Sound like this" not in prompt


def test_system_prompt_includes_the_current_time(tmp_path):
    from datetime import datetime, timezone

    from jarvis.config import AssistantConfig

    assistant = AssistantConfig(name="JARVIS", purpose="help", tone="crisp")
    moment = datetime(2026, 10, 2, 14, 30, tzinfo=timezone.utc)
    prompt = build_system_prompt(assistant, now=moment)
    assert "2026" in prompt
    assert "Current time:" in prompt
