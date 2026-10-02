"""Gemini brain — the provider seam implemented against the Gemini REST API.

Uses `streamGenerateContent` with server-sent events so the reply can be spoken
as it is written (Tier 3) rather than after it is finished.
"""

from __future__ import annotations

import json
from typing import Iterator, Sequence

import httpx

from .base import Message, ProviderError, StreamEvent, TextDelta, TurnEnd

# Gemini calls the assistant's turn "model", not "assistant".
_ROLE_MAP = {"user": "user", "assistant": "model"}


class GeminiProvider:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        temperature: float,
        max_output_tokens: int,
        timeout_seconds: float,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout = httpx.Timeout(timeout_seconds, connect=15.0)

    def _payload(self, system: str, messages: Sequence[Message]) -> dict:
        return {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [
                {
                    "role": _ROLE_MAP.get(m.role, "user"),
                    "parts": [{"text": m.content}],
                }
                for m in messages
            ],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_output_tokens,
            },
        }

    def stream(self, system: str, messages: Sequence[Message]) -> Iterator[StreamEvent]:
        url = f"{self.base_url}/models/{self.model}:streamGenerateContent"
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }

        usage: dict | None = None
        try:
            with httpx.stream(
                "POST",
                url,
                params={"alt": "sse"},
                headers=headers,
                json=self._payload(system, messages),
                timeout=self.timeout,
            ) as response:
                if response.status_code != 200:
                    raise ProviderError(self._explain(response))

                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue  # tolerate a malformed keep-alive frame

                    block = (chunk.get("promptFeedback") or {}).get("blockReason")
                    if block:
                        raise ProviderError(
                            f"the model declined this request (blocked: {block})"
                        )

                    for candidate in chunk.get("candidates") or []:
                        for part in (candidate.get("content") or {}).get("parts") or []:
                            text = part.get("text")
                            if text:
                                yield TextDelta(text)

                    if chunk.get("usageMetadata"):
                        usage = chunk["usageMetadata"]

        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"the model did not respond within {self.timeout.read:.0f}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"could not reach the model: {exc}") from exc

        yield TurnEnd(usage=usage)

    @staticmethod
    def _explain(response: httpx.Response) -> str:
        """Turn an HTTP failure into something worth reading."""
        try:
            detail = response.read().decode("utf-8", "replace")
            parsed = json.loads(detail)
            detail = (parsed.get("error") or {}).get("message") or detail
        except Exception:
            detail = ""
        detail = (detail or "").strip()[:300]

        if response.status_code in (400, 401, 403):
            hint = "check that GEMINI_API_KEY is valid and has access to this model"
        elif response.status_code == 404:
            hint = "the model name may be wrong or retired — see config.yaml"
        elif response.status_code == 429:
            hint = "rate limited — wait a moment and try again"
        elif response.status_code >= 500:
            hint = "the provider is having trouble — try again shortly"
        else:
            hint = "unexpected response from the provider"

        return f"model request failed ({response.status_code}): {hint}" + (
            f" — {detail}" if detail else ""
        )
