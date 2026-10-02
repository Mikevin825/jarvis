"""Ollama brain — a local, offline implementation of the same provider seam.

Needs no API key. Useful for developing and verifying the harness without a
cloud account, and as a fallback when the network is down.
"""

from __future__ import annotations

import json
from typing import Iterator, Sequence

import httpx

from .base import Message, ProviderError, StreamEvent, TextDelta, TurnEnd


class OllamaProvider:
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        temperature: float,
        timeout_seconds: float,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        # Local models can be slow to load on first call; allow a long read.
        self.timeout = httpx.Timeout(timeout_seconds, connect=5.0)

    def _payload(self, system: str, messages: Sequence[Message]) -> dict:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                *[{"role": m.role, "content": m.content} for m in messages],
            ],
            "stream": True,
            "options": {"temperature": self.temperature},
        }

    def stream(self, system: str, messages: Sequence[Message]) -> Iterator[StreamEvent]:
        url = f"{self.base_url}/api/chat"
        try:
            with httpx.stream(
                "POST",
                url,
                json=self._payload(system, messages),
                timeout=self.timeout,
            ) as response:
                if response.status_code != 200:
                    detail = response.read().decode("utf-8", "replace")[:300]
                    raise ProviderError(
                        f"ollama returned {response.status_code}"
                        + (f" — {detail.strip()}" if detail.strip() else "")
                    )

                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        raise ProviderError(f"ollama: {chunk['error']}")
                    text = (chunk.get("message") or {}).get("content")
                    if text:
                        yield TextDelta(text)
                    if chunk.get("done"):
                        break

        except httpx.ConnectError as exc:
            raise ProviderError(
                f"no local model is listening at {self.base_url}.\n"
                "  Start it with: ollama serve"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"the local model did not respond within {self.timeout.read:.0f}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"could not reach the local model: {exc}") from exc

        yield TurnEnd(usage=None)
