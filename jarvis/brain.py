"""The brain — a conversation loop.

Takes a turn of input, appends it to the running history, sends the whole
conversation plus the system prompt to the provider, streams the reply back, and
appends the reply to the history. This is the one core every entry point uses:
typed turns now, spoken turns in Tier 3, heartbeat-initiated turns in Tier 5.

History is in memory only. It is short-term memory; Tier 4 adds the long-term
store that survives a restart.
"""

from __future__ import annotations

from typing import Iterator, Sequence

from .providers import Message, Provider, ProviderError, TextDelta


class Brain:
    def __init__(self, provider: Provider, system_prompt: str) -> None:
        self.provider = provider
        self.system_prompt = system_prompt
        self.history: list[Message] = []

    def ask(self, user_text: str) -> Iterator[str]:
        """Run one turn, yielding the reply in chunks as it is generated.

        On failure the history is left consistent: a partial reply is kept only
        if some of it was already shown, otherwise the failed user turn is
        dropped so the next attempt starts clean.
        """
        self.history.append(Message(role="user", content=user_text))
        parts: list[str] = []

        try:
            for event in self.provider.stream(self.system_prompt, self.history):
                if isinstance(event, TextDelta):
                    parts.append(event.text)
                    yield event.text
        except ProviderError:
            if parts:
                self.history.append(
                    Message(role="assistant", content="".join(parts))
                )
            else:
                self.history.pop()
            raise

        self.history.append(Message(role="assistant", content="".join(parts)))

    def reset(self) -> None:
        """Forget the current session. Long-term memory (Tier 4) is unaffected."""
        self.history.clear()

    @property
    def turns(self) -> int:
        return len(self.history)

    def transcript(self) -> Sequence[Message]:
        return tuple(self.history)
