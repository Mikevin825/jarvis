"""The brain: one core, and it must not fall over when the model does."""

from __future__ import annotations

import pytest

from jarvis.brain import Brain
from jarvis.providers import (
    FunctionCall,
    ProviderError,
    TextDelta,
    TurnEnd,
)


class ScriptedProvider:
    """Replays a fixed list of turns."""

    supports_tools = True

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    def stream(self, system, messages, tools=None, max_tokens=None):
        self.calls.append(list(messages))
        turn = self.turns.pop(0) if self.turns else TurnEnd(text="", raw=None, calls=[])
        if isinstance(turn, Exception):
            raise turn
        for chunk in turn.get("text", []):
            yield TextDelta(chunk)
        yield TurnEnd(
            text="".join(turn.get("text", [])),
            calls=turn.get("calls", []),
            raw=None,
        )


def test_reply_is_streamed_in_chunks():
    provider = ScriptedProvider([{"text": ["Hel", "lo ", "there"]}])
    brain = Brain(provider, "sys")
    chunks = [e.text for e in brain.ask("hi")]
    assert chunks == ["Hel", "lo ", "there"]


def test_history_is_passed_back_so_it_remembers():
    """Tier 1's core property: turn 1 is visible at turn 3."""
    provider = ScriptedProvider([{"text": ["one"]}, {"text": ["two"]}, {"text": ["three"]}])
    brain = Brain(provider, "sys")
    list(brain.ask("first"))
    list(brain.ask("second"))
    list(brain.ask("third"))

    final = provider.calls[-1]
    contents = [m.content for m in final]
    assert "first" in contents
    assert "one" in contents
    assert "third" in contents


def test_reset_clears_the_session():
    provider = ScriptedProvider([{"text": ["a"]}])
    brain = Brain(provider, "sys")
    list(brain.ask("hi"))
    assert brain.turns == 2
    brain.reset()
    assert brain.turns == 0


def test_tool_call_is_executed_and_fed_back(registry):
    provider = ScriptedProvider(
        [
            {"text": [], "calls": [FunctionCall(name="get_current_time", args={})]},
            {"text": ["It is now."]},
        ]
    )
    brain = Brain(provider, "sys", registry)
    events = list(brain.ask("what time is it"))

    tool_runs = [e for e in events if hasattr(e, "name")]
    assert len(tool_runs) == 1
    assert tool_runs[0].ok is True
    # The second request must carry the tool output.
    second = provider.calls[1]
    assert any(m.outputs for m in second)


def test_multiple_tools_in_one_turn(registry):
    provider = ScriptedProvider(
        [
            {
                "text": [],
                "calls": [
                    FunctionCall(name="get_current_time", args={}),
                    FunctionCall(name="list_notes", args={}),
                ],
            },
            {"text": ["Both done."]},
        ]
    )
    brain = Brain(provider, "sys", registry)
    events = list(brain.ask("time and notes"))
    assert len([e for e in events if hasattr(e, "name")]) == 2


def test_a_failing_tool_does_not_crash_the_turn(registry):
    """A tool that fails must not take the turn down with it.

    The follow-up reply is the real assertion: the brain ran the tool, saw it
    fail, and still produced an answer. The error text is deliberately not
    asserted — the weather service can answer "city not found" or time out, and
    both are legitimate failures that this test does not care about.
    """
    provider = ScriptedProvider(
        [
            {
                "text": [],
                "calls": [FunctionCall(name="get_weather", args={"city": "Qzxwvplkk"})],
            },
            {"text": ["I could not find that place."]},
        ]
    )
    brain = Brain(provider, "sys", registry)
    events = list(brain.ask("weather in nowhere"))
    runs = [e for e in events if hasattr(e, "name")]
    assert runs[0].ok is False
    assert runs[0].content, "a failed tool should still report why"

    # The brain recovered and answered rather than raising.
    replies = [e for e in events if hasattr(e, "text") and e.text]
    assert any("could not find that place" in r.text for r in replies)


def test_unknown_tool_is_reported_not_raised(registry):
    provider = ScriptedProvider(
        [
            {"text": [], "calls": [FunctionCall(name="launch_missiles", args={})]},
            {"text": ["No such tool."]},
        ]
    )
    brain = Brain(provider, "sys", registry)
    events = list(brain.ask("fire"))
    runs = [e for e in events if hasattr(e, "name")]
    assert runs[0].ok is False
    assert "no tool" in runs[0].content.lower()


def test_runaway_tool_loop_is_bounded(registry):
    """A model stuck in a loop must be stopped, not hammer the provider."""
    class AlwaysCalls:
        supports_tools = True

        def stream(self, system, messages, tools=None, max_tokens=None):
            yield TurnEnd(
                text="",
                calls=[FunctionCall(name="get_current_time", args={})],
                raw=None,
            )

    brain = Brain(AlwaysCalls(), "sys", registry, max_tool_rounds=3)
    events = list(brain.ask("go"))
    assert any("stopped after" in getattr(e, "text", "") for e in events)


def test_provider_failure_leaves_history_consistent(registry):
    provider = ScriptedProvider([ProviderError("model is down")])
    brain = Brain(provider, "sys", registry)

    with pytest.raises(ProviderError):
        list(brain.ask("hello"))

    assert brain.turns == 0, "a failed turn must not leave a half-written history"


def test_provider_failure_after_output_keeps_what_was_shown(registry):
    class FailsMidway:
        supports_tools = True

        def stream(self, system, messages, tools=None, max_tokens=None):
            yield TextDelta("I was saying")
            raise ProviderError("dropped")

    brain = Brain(FailsMidway(), "sys", registry)
    with pytest.raises(ProviderError):
        list(brain.ask("hello"))

    # What the user saw is in the transcript; the turn is not left half-open.
    assert brain.turns == 2
    assert brain.transcript()[-1].content == "I was saying"


def test_tool_output_is_wrapped_as_untrusted(registry):
    """Content from a tool must reach the model marked as data."""
    provider = ScriptedProvider(
        [
            {"text": [], "calls": [FunctionCall(name="get_weather", args={"city": "Lagos"})]},
            {"text": ["ok"]},
        ]
    )
    brain = Brain(provider, "sys", registry)
    list(brain.ask("weather"))

    second = provider.calls[1]
    tool_messages = [m for m in second if m.outputs]
    assert tool_messages, "a tool result must be present"
    assert "UNTRUSTED CONTENT" in tool_messages[0].outputs[0].content
