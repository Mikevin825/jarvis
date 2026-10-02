"""The provider seam.

This is the single boundary between the harness and whatever model is doing the
thinking. Everything else in the codebase calls `Provider.stream` and nothing
else ever touches a provider's SDK or HTTP shape. That is what makes it cheap to
swap models, add retries, or log costs later — all in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Literal, Protocol, Sequence

Role = Literal["user", "assistant", "tool"]


class ProviderError(RuntimeError):
    """The brain was unreachable, refused us, or returned something unusable.

    Carries a message that is safe and useful to show a human directly.
    """


@dataclass
class FunctionCall:
    """A request from the model to run one tool."""

    name: str
    args: dict


@dataclass
class ToolOutput:
    """The result of running a tool, on its way back to the model."""

    name: str
    content: str
    ok: bool = True


@dataclass
class Message:
    """One turn of conversation, in a provider-neutral shape.

    A message carries text, the tool calls the model made, or the outputs of
    tools that were run.
    """

    role: Role
    content: str = ""
    calls: list[FunctionCall] = field(default_factory=list)
    outputs: list[ToolOutput] = field(default_factory=list)
    # Opaque, provider-specific payload needed to replay this message verbatim.
    # Gemini 3 attaches a thought signature to each function call and rejects
    # the follow-up request if it is not echoed back, so the raw parts are kept.
    raw: Any = None


@dataclass
class TextDelta:
    """A chunk of the reply, as it is generated."""

    text: str


@dataclass
class TurnEnd:
    """The end of one model turn.

    Carries everything the loop needs to decide what happens next: the full text,
    any tool calls the model wants run, and usage metadata (Tier 6 turns that
    into a running cost tally).
    """

    usage: dict | None = None
    text: str = ""
    calls: list[FunctionCall] = field(default_factory=list)
    raw: Any = None


StreamEvent = TextDelta | TurnEnd


class Provider(Protocol):
    """Send this conversation, get back a reply.

    Implementations must stream: yield `TextDelta` as text arrives, then exactly
    one `TurnEnd`. They must raise `ProviderError` — never leak httpx or SDK
    exceptions — so the loop above can stay simple.

    `tools` is the registry's declaration list, or None when the caller wants a
    plain text turn (the heartbeat does this in Tier 5).
    """

    supports_tools: bool

    def stream(
        self,
        system: str,
        messages: Sequence[Message],
        tools: list[dict] | None = None,
    ) -> Iterator[StreamEvent]:  # pragma: no cover - protocol
        ...
