"""The brain — the conversation loop.

Takes a turn of input, appends it to the running history, sends the whole
conversation plus the system prompt to the provider, streams the reply back, and
appends the reply to the history. This is the one core every entry point uses:
typed turns now, spoken turns in Tier 3, heartbeat-initiated turns in Tier 5.

The loop is where tools live. The model may call several tools in a row before
it is ready to answer — it is never assumed to be one call per turn. A tool that
fails returns its error to the model as a result, so the agent can reason about
the failure and explain it, rather than the loop crashing.

History is in memory only. It is short-term memory; Tier 4 adds the long-term
store that survives a restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, Sequence

from .providers import (
    FunctionCall,
    Message,
    Provider,
    ProviderError,
    TextDelta,
    ToolOutput,
    TurnEnd,
)
from .tools import ToolRegistry

DEFAULT_MAX_TOOL_ROUNDS = 8

# Given the turn's text, return the facts worth showing the model. Returning ""
# means "nothing remembered", which keeps the prompt free of an empty section.
MemorySelector = Callable[[str], str]


@dataclass
class Chunk:
    """A piece of the assistant's reply, to be shown or spoken."""

    text: str


@dataclass
class ToolRun:
    """A tool the model chose to run, and what came back.

    Surfaced to the interface so the user can see what JARVIS actually did —
    the beginnings of the audit trail that Tier 6 formalises.
    """

    name: str
    args: dict
    ok: bool
    content: str


BrainEvent = Chunk | ToolRun


class Brain:
    def __init__(
        self,
        provider: Provider,
        system_prompt: str,
        registry: ToolRegistry | None = None,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
        memory_selector: MemorySelector | None = None,
        prompt_builder: Callable[[str], str] | None = None,
    ) -> None:
        self.provider = provider
        self.system_prompt = system_prompt
        self.registry = registry
        self.max_tool_rounds = max_tool_rounds
        # Long-term memory, refreshed at the start of every turn. Recomputing it
        # per turn is what lets JARVIS use a fact it learned moments ago, and it
        # also means a hand edit to the memory file is picked up without a
        # restart. Both are worth the trivial cost.
        self.memory_selector = memory_selector
        self.prompt_builder = prompt_builder
        self.history: list[Message] = []

    # -- public -------------------------------------------------------------

    def current_system_prompt(self, turn_text: str = "") -> str:
        """The system prompt for this turn, including relevant memory."""
        if self.prompt_builder is None:
            return self.system_prompt
        if self.memory_selector is None:
            return self.prompt_builder("")
        try:
            facts = self.memory_selector(turn_text)
        except Exception:  # noqa: BLE001 - memory must never break a conversation
            facts = ""
        return self.prompt_builder(facts)

    def ask(self, user_text: str) -> Iterator[BrainEvent]:
        """Run one turn, yielding the reply and any tool activity as it happens.

        If the model becomes unreachable mid-turn the history is rolled back to
        a consistent state — a half-finished tool exchange left in the log would
        break the *next* request too.
        """
        start = len(self.history)
        self.history.append(Message(role="user", content=user_text))
        spoken: list[str] = []

        try:
            for event in self._run(user_text, spoken):
                yield event
        except ProviderError:
            del self.history[start:]
            if spoken:
                # Keep what was already shown to the user, so the transcript
                # matches what they saw.
                self.history.append(Message(role="user", content=user_text))
                self.history.append(
                    Message(role="assistant", content="".join(spoken))
                )
            raise

    def reset(self) -> None:
        """Forget the current session. Long-term memory (Tier 4) is unaffected."""
        self.history.clear()

    @property
    def turns(self) -> int:
        return len(self.history)

    def transcript(self) -> Sequence[Message]:
        return tuple(self.history)

    # -- internals ----------------------------------------------------------

    def _run(self, user_text: str, spoken: list[str]) -> Iterator[BrainEvent]:
        tools = self.registry.declarations() if self.registry else None
        system = self.current_system_prompt(user_text)

        for round_index in range(self.max_tool_rounds + 1):
            end = yield from self._one_turn(system, tools, spoken)

            self.history.append(
                Message(
                    role="assistant",
                    content=end.text,
                    calls=end.calls,
                    raw=end.raw,
                )
            )

            if not end.calls:
                return  # a normal answer — the turn is done

            if round_index >= self.max_tool_rounds:
                # Runaway guard: something is looping. Stop cleanly and say so
                # rather than hammering the provider or the tools forever.
                note = (
                    f"[stopped after {self.max_tool_rounds} rounds of tool calls "
                    "without a final answer]"
                )
                spoken.append(note)
                yield Chunk("\n" + note)
                return

            outputs: list[ToolOutput] = []
            for call in end.calls:
                result = self.registry.run(call.name, call.args)
                yield ToolRun(
                    name=call.name,
                    args=call.args,
                    ok=result.ok,
                    content=result.content,
                )
                outputs.append(
                    ToolOutput(name=call.name, content=result.content, ok=result.ok)
                )
            self.history.append(Message(role="tool", outputs=outputs))

    def _one_turn(
        self, system: str, tools: list[dict] | None, spoken: list[str]
    ) -> Iterator[BrainEvent]:
        """Stream one model turn and return its `TurnEnd`."""
        end: TurnEnd | None = None
        for event in self.provider.stream(system, self.history, tools):
            if isinstance(event, TextDelta):
                spoken.append(event.text)
                yield Chunk(event.text)
            elif isinstance(event, TurnEnd):
                end = event

        if end is None:
            raise ProviderError("the model returned nothing at all")
        return end
