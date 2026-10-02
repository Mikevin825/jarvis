"""Ollama brain — a local, offline implementation of the same provider seam.

Needs no API key. Useful for developing and verifying the harness without a
cloud account, and as a fallback when the network is down.

Note: small local models are much less reliable at choosing tools than the cloud
brain, so this is a development path rather than the daily driver.
"""

from __future__ import annotations

import json
from typing import Iterator, Sequence

import httpx

from .base import (
    FunctionCall,
    Message,
    ProviderError,
    StreamEvent,
    TextDelta,
    TurnEnd,
)


class OllamaProvider:
    supports_tools = True

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

    def _messages(self, system: str, messages: Sequence[Message]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m.outputs:
                for o in m.outputs:
                    out.append({"role": "tool", "content": o.content})
            elif m.calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": m.content or "",
                        "tool_calls": [
                            {"function": {"name": c.name, "arguments": c.args}}
                            for c in m.calls
                        ],
                    }
                )
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    def stream(
        self,
        system: str,
        messages: Sequence[Message],
        tools: list[dict] | None = None,
    ) -> Iterator[StreamEvent]:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": self._messages(system, messages),
            "stream": True,
            "options": {"temperature": self.temperature},
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["parameters"],
                    },
                }
                for t in tools
            ]

        calls: list[FunctionCall] = []
        text_parts: list[str] = []

        try:
            with httpx.stream(
                "POST", url, json=payload, timeout=self.timeout
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

                    message = chunk.get("message") or {}
                    text = message.get("content")
                    if text:
                        text_parts.append(text)
                        yield TextDelta(text)

                    for tc in message.get("tool_calls") or []:
                        fn = tc.get("function") or {}
                        args = fn.get("arguments") or {}
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {}
                        calls.append(FunctionCall(name=fn.get("name", ""), args=args))

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

        yield TurnEnd(usage=None, text="".join(text_parts), calls=calls, raw=None)
