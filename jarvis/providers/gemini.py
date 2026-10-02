"""Gemini brain — the provider seam implemented against the Gemini REST API.

Uses `streamGenerateContent` with server-sent events so the reply can be spoken
as it is written (Tier 3) rather than after it is finished.

One Gemini-specific detail that matters: Gemini 3 returns a `thoughtSignature`
alongside each function call and **rejects the follow-up request** if the call is
replayed without it. So a model turn is stored verbatim in `Message.raw` and
sent back exactly as received.
"""

from __future__ import annotations

import json
import time
from typing import Any, Iterator, Sequence

import httpx

from .base import (
    FunctionCall,
    Message,
    ProviderError,
    StreamEvent,
    TextDelta,
    TurnEnd,
)

# Gemini calls the assistant's turn "model", not "assistant".
_ROLE_MAP = {"user": "user", "assistant": "model", "tool": "user"}


class _TransientProviderError(ProviderError):
    """A failure worth retrying: overload, or a genuine rate limit.

    Deliberately *not* used for a quota-exhausted 429 — retrying that just burns
    time, because the limit will not clear within the backoff window.
    """


def _retryable(exc: ProviderError) -> bool:
    return isinstance(exc, _TransientProviderError)


class GeminiProvider:
    supports_tools = True

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        temperature: float,
        max_output_tokens: int,
        timeout_seconds: float,
        max_retries: int = 3,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout = httpx.Timeout(timeout_seconds, connect=15.0)
        self.max_retries = max_retries

    # -- request building ---------------------------------------------------

    def _parts_for(self, message: Message) -> list[dict]:
        """Turn one neutral message into Gemini `parts`."""
        if message.raw is not None:
            # Replaying a model turn: send back exactly what came in, including
            # thought signatures, or the API rejects the call.
            return message.raw

        if message.outputs:
            return [
                {
                    "functionResponse": {
                        "name": out.name,
                        "response": (
                            {"result": out.content}
                            if out.ok
                            else {"error": out.content}
                        ),
                    }
                }
                for out in message.outputs
            ]

        if message.calls:
            return [
                {"functionCall": {"name": c.name, "args": c.args}}
                for c in message.calls
            ]

        return [{"text": message.content}]

    def _payload(
        self, system: str, messages: Sequence[Message], tools: list[dict] | None
    ) -> dict:
        payload: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [
                {"role": _ROLE_MAP.get(m.role, "user"), "parts": self._parts_for(m)}
                for m in messages
            ],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_output_tokens,
            },
        }
        if tools:
            payload["tools"] = [{"functionDeclarations": tools}]
        return payload

    # -- streaming ----------------------------------------------------------

    def stream(
        self,
        system: str,
        messages: Sequence[Message],
        tools: list[dict] | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream one turn, retrying transient provider failures.

        Only safe to retry because nothing is yielded until the connection is
        established and streaming has begun: if we fail before the first chunk,
        the caller has seen nothing, so a retry cannot duplicate output.
        """
        last: ProviderError | None = None
        for attempt in range(self.max_retries):
            started = False
            try:
                for event in self._stream_once(system, messages, tools):
                    if isinstance(event, TextDelta):
                        started = True
                    yield event
                return
            except ProviderError as exc:
                last = exc
                if started or not _retryable(exc) or attempt == self.max_retries - 1:
                    raise
                # Back off a little: 1s, then 2s.
                time.sleep(2**attempt)

        raise last  # pragma: no cover - unreachable

    def _stream_once(
        self,
        system: str,
        messages: Sequence[Message],
        tools: list[dict] | None,
    ) -> Iterator[StreamEvent]:
        url = f"{self.base_url}/models/{self.model}:streamGenerateContent"
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }

        usage: dict | None = None
        # Collected so the brain can replay this turn exactly (see `raw` above).
        collected: list[dict] = []
        text_parts: list[str] = []
        calls: list[FunctionCall] = []

        try:
            with httpx.stream(
                "POST",
                url,
                params={"alt": "sse"},
                headers=headers,
                json=self._payload(system, messages, tools),
                timeout=self.timeout,
            ) as response:
                if response.status_code != 200:
                    raise self._failure(response)

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
                            collected.append(part)
                            text = part.get("text")
                            if text:
                                text_parts.append(text)
                                yield TextDelta(text)
                            fc = part.get("functionCall")
                            if fc:
                                calls.append(
                                    FunctionCall(
                                        name=fc.get("name", ""),
                                        args=fc.get("args") or {},
                                    )
                                )

                    if chunk.get("usageMetadata"):
                        usage = chunk["usageMetadata"]

        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"the model did not respond within {self.timeout.read:.0f}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"could not reach the model: {exc}") from exc

        yield TurnEnd(
            usage=usage,
            text="".join(text_parts),
            calls=calls,
            raw=collected or None,
        )

    # -- helpers ------------------------------------------------------------

    def _explain(self, response: httpx.Response) -> str:
        """Turn an HTTP failure into something worth reading.

        Returns the message; the caller wraps it in a transient or permanent
        error depending on whether retrying could plausibly help.
        """
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
            # Two very different causes, and they need different fixes. The
            # per-model case is the one that bites: a key can be perfectly
            # valid and still have zero quota for a given model.
            if "quota" in detail.lower():
                hint = (
                    f"no quota for '{self.model}' on this key's tier. This is a "
                    "per-model or daily limit, not a broken key — try a different "
                    "model in config.yaml (brain.gemini.model), or wait for the "
                    "daily reset at midnight Pacific"
                )
            else:
                hint = "rate limited — wait a moment and try again"
        elif response.status_code == 503:
            hint = (
                f"'{self.model}' is temporarily overloaded at the provider — "
                "try again shortly, or pick another model in config.yaml"
            )
        elif response.status_code >= 500:
            hint = "the provider is having trouble — try again shortly"
        else:
            hint = "unexpected response from the provider"

        return f"model request failed ({response.status_code}): {hint}" + (
            f" — {detail}" if detail else ""
        )

    def _failure(self, response: httpx.Response) -> ProviderError:
        """Classify a failed response as transient or permanent."""
        message = self._explain(response)
        if response.status_code == 503 or response.status_code >= 500:
            return _TransientProviderError(message)
        if response.status_code == 429 and "quota" not in message.lower():
            return _TransientProviderError(message)
        return ProviderError(message)
