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
from .untrusted import wrap_untrusted

DEFAULT_MAX_TOOL_ROUNDS = 8

# Which sub-agent a tool belongs to, so the galaxy's constellation can light up
# the right avatar when that tool runs. Tools not listed here drive no agent —
# a clock lookup is not the Scout's work.
AGENT_FOR_TOOL: dict[str, str] = {
    # Scout's hunting tools
    "fetch_web": "scout",
    "search_web": "scout",
    "web_search": "scout",
    "read_page": "scout",
    # Board's tools
    "convene_board": "board",
    "list_board": "board",
    # Mind's tools — the memory and knowledge surface
    "remember_fact": "mindmap",
    "save_memory": "mindmap",
    "recall_memory": "mindmap",
    "list_facts": "mindmap",
    "update_fact": "mindmap",
    "forget_fact": "mindmap",
    "list_notes": "mindmap",
    "read_note": "mindmap",
    "write_note": "mindmap",
}

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
    # True when the gate blocked it, so the interface can say "declined" rather
    # than showing it as a plain failure.
    gated: bool = False


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
        on_usage: Callable[[dict], None] | None = None,
        voice_cue: Callable[[], str] | None = None,
        galaxy=None,
    ) -> None:
        self.provider = provider
        self.system_prompt = system_prompt
        self.registry = registry
        self.max_tool_rounds = max_tool_rounds
        # The galaxy bridge, if one is wired. Used to tell the constellation
        # which sub-agent is working; None means the galaxy is not running.
        self.galaxy = galaxy
        # Long-term memory, refreshed at the start of every turn. Recomputing it
        # per turn is what lets JARVIS use a fact it learned moments ago, and it
        # also means a hand edit to the memory file is picked up without a
        # restart. Both are worth the trivial cost.
        self.memory_selector = memory_selector
        self.prompt_builder = prompt_builder
        # Usage from the most recent provider call, for the cost tally.
        self.last_usage: dict | None = None
        self.on_usage = on_usage
        # The per-turn voice reminder. Appended to the last user message on its
        # way to the model and never stored in history — see the comment in
        # `_with_voice_cue`.
        self.voice_cue = voice_cue
        self._dynamic_block = ""
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

    def set_dynamic_block(self, dynamic: str) -> None:
        """Set the dynamic block to prepend to the first user message."""
        self._dynamic_block = dynamic

    def ask(self, user_text: str) -> Iterator[BrainEvent]:
        """Run one turn, yielding the reply and any tool activity as it happens.

        If the model becomes unreachable mid-turn the history is rolled back to
        a consistent state — a half-finished tool exchange left in the log would
        break the *next* request too.
        """
        start = len(self.history)
        self.history.append(Message(role="user", content=user_text))
        spoken: list[str] = []

        # Tell the galaxy we're thinking
        if self.galaxy is not None:
            try:
                self.galaxy.set_state("thinking")
            except Exception:
                pass

        try:
            for event in self._run(user_text, spoken):
                # Tell the galaxy we're speaking when we yield text
                if isinstance(event, Chunk) and self.galaxy is not None:
                    try:
                        self.galaxy.set_state("speaking")
                    except Exception:
                        pass
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
        finally:
            # Tell the galaxy we're done
            if self.galaxy is not None:
                try:
                    self.galaxy.set_state("idle")
                except Exception:
                    pass

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
                # Tell the galaxy which sub-agent is being dispatched, so the
                # constellation can fire a beam before the tool even returns.
                if self.galaxy is not None:
                    agent = AGENT_FOR_TOOL.get(call.name)
                    if agent is not None:
                        self.galaxy.emit_dispatch(agent)
                        self.galaxy.emit_working(agent, True)

                result = self.registry.run(call.name, call.args)

                if self.galaxy is not None:
                    agent = AGENT_FOR_TOOL.get(call.name)
                    if agent is not None:
                        self.galaxy.emit_working(agent, False)

                yield ToolRun(
                    name=call.name,
                    args=call.args,
                    ok=result.ok,
                    content=result.content,
                    gated=getattr(result, "gated", False),
                )
                # Everything a tool returns is content from outside this
                # conversation, so it is wrapped and marked as data. A tool that
                # reads a web page or a file is exactly how an instruction-shaped
                # string would otherwise reach the model as if the user said it.
                outputs.append(
                    ToolOutput(
                        name=call.name,
                        content=wrap_untrusted(result.content, f"tool:{call.name}"),
                        ok=result.ok,
                    )
                )
            self.history.append(Message(role="tool", outputs=outputs))

    def _with_voice_cue(self, history: list[Message]) -> list[Message]:
        """Append the voice reminder to the last user message, for the API only.

        This is the anti-drift mechanism, and the *position* is the point.

        As a conversation grows, the assistant's own prior replies become the
        strongest behavioural signal and progressively outweigh the personality
        block at the top of the system prompt. Once one reply slips into generic
        assistant phrasing, that reply becomes the reference for the next, and
        the slide compounds. A reminder at the top cannot win that contest; a
        reminder sitting *after* every prior assistant turn can.

        The cue is added to a copy that goes to the provider and is deliberately
        never written back to `self.history`. Storing it would (a) bloat the
        transcript, and (b) turn it into another prior assistant turn for the
        model to imitate, which is the opposite of what it is for.
        """
        if self.voice_cue is None or not history:
            return history

        try:
            cue = self.voice_cue()
        except Exception:  # noqa: BLE001 - a broken cue must not stop a reply
            return history
        if not cue:
            return history

        # Find the last user message. Tool rounds end with a tool message, so
        # walking back is necessary; the cue belongs with the human's turn.
        for index in range(len(history) - 1, -1, -1):
            message = history[index]
            if message.role == "user" and message.content and not message.outputs:
                patched = list(history)
                patched[index] = Message(
                    role=message.role,
                    content=f"{message.content}\n\n{cue}",
                    calls=message.calls,
                    outputs=message.outputs,
                    raw=message.raw,
                )
                return patched
        return history

    def _one_turn(
        self, system: str, tools: list[dict] | None, spoken: list[str]
    ) -> Iterator[BrainEvent]:
        """Stream one model turn and return its `TurnEnd`."""
        end: TurnEnd | None = None
        outbound = self._with_voice_cue(self.history)
        # Prepend dynamic block to first user message (always fresh)
        if self._dynamic_block and outbound:
            first = outbound[0]
            if first.role == "user":
                outbound = list(outbound)
                outbound[0] = Message(
                    role=first.role,
                    content=f"{self._dynamic_block}\n\n{first.content}",
                    calls=first.calls,
                    outputs=first.outputs,
                    raw=first.raw,
                )
        for event in self.provider.stream(system, outbound, tools):
            if isinstance(event, TextDelta):
                spoken.append(event.text)
                yield Chunk(event.text)
            elif isinstance(event, TurnEnd):
                end = event
                # Record usage for every call, not just the last, so a turn
                # that ran several tool rounds is not undercounted.
                if event.usage:
                    self.last_usage = event.usage
                    if self.on_usage is not None:
                        try:
                            self.on_usage(event.usage)
                        except Exception:  # noqa: BLE001
                            pass

        if end is None:
            raise ProviderError("the model returned nothing at all")
        return end
