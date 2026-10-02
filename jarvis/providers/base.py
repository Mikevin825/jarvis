"""The provider seam.

This is the single boundary between the harness and whatever model is doing the
thinking. Everything else in the codebase calls `Provider.stream` and nothing
else ever touches a provider's SDK or HTTP shape. That is what makes it cheap to
swap models, add retries, or log costs later — all in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Literal, Protocol, Sequence

Role = Literal["user", "assistant"]


class ProviderError(RuntimeError):
    """The brain was unreachable, refused us, or returned something unusable.

    Carries a message that is safe and useful to show a human directly.
    """


@dataclass
class Message:
    """One turn of conversation, in a provider-neutral shape."""

    role: Role
    content: str


@dataclass
class TextDelta:
    """A chunk of the reply, as it is generated."""

    text: str


@dataclass
class TurnEnd:
    """Signals the end of a model turn, with any usage metadata we captured.

    Tier 6 turns `usage` into a running cost tally.
    """

    usage: dict | None = None


StreamEvent = TextDelta | TurnEnd


class Provider(Protocol):
    """Send this conversation, get back a reply.

    Implementations must stream: yield `TextDelta` as text arrives, then exactly
    one `TurnEnd`. They must raise `ProviderError` — never leak httpx or SDK
    exceptions — so the loop above can stay simple.
    """

    def stream(
        self, system: str, messages: Sequence[Message]
    ) -> Iterator[StreamEvent]:  # pragma: no cover - protocol
        ...
