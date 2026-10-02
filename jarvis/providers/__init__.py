"""Provider implementations, selected by `brain.provider` in config.yaml."""

from __future__ import annotations

from ..config import BrainConfig
from .base import (
    FunctionCall,
    Message,
    Provider,
    ProviderError,
    StreamEvent,
    TextDelta,
    ToolOutput,
    TurnEnd,
)

__all__ = [
    "FunctionCall",
    "Message",
    "Provider",
    "ProviderError",
    "StreamEvent",
    "TextDelta",
    "ToolOutput",
    "TurnEnd",
    "build_provider",
]


def build_provider(cfg: BrainConfig) -> Provider:
    """Construct the provider named in the config.

    Adding a new brain means adding a module next to this one and a branch here
    — no other file changes.
    """
    if cfg.provider == "gemini":
        from .gemini import GeminiProvider

        if not cfg.api_key:
            raise ProviderError(
                "brain.provider is 'gemini' but no API key was found.\n"
                "  Fix: copy .env.example to .env and set GEMINI_API_KEY,\n"
                "  or set brain.provider: ollama in config.yaml to run locally."
            )
        return GeminiProvider(
            model=cfg.model,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            temperature=cfg.temperature,
            max_output_tokens=cfg.max_output_tokens,
            timeout_seconds=cfg.timeout_seconds,
        )

    if cfg.provider == "ollama":
        from .ollama import OllamaProvider

        return OllamaProvider(
            model=cfg.model,
            base_url=cfg.base_url,
            temperature=cfg.temperature,
            timeout_seconds=cfg.timeout_seconds,
        )

    raise ProviderError(f"unknown brain.provider: {cfg.provider!r}")
