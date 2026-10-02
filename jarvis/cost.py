"""A running tally of model usage.

The point is visibility: a runaway loop — a retry storm, a tool cycle, an
accidental overnight heartbeat — should be obvious immediately rather than
discovered on a bill. Cost is tracked per session and persisted as a lifetime
total.

Prices are per million tokens and are *configurable*, because they change. The
figures here are only used to make the tally meaningful; the token counts
themselves are exact, straight from the provider.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# USD per 1M tokens. Override in config if these drift.
DEFAULT_PRICES = {
    "gemini-3.5-flash": (0.30, 2.50),
    "gemini-3.5-flash-lite": (0.10, 0.40),
    "gemini-3.6-flash": (0.30, 2.50),
    "gemini-3.1-pro-preview": (1.25, 10.00),
    "default": (0.30, 2.50),
}


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class CostTracker:
    path: Path | None = None
    model: str = ""
    prices: dict = field(default_factory=lambda: dict(DEFAULT_PRICES))
    session: Usage = field(default_factory=Usage)
    lifetime: Usage = field(default_factory=Usage)

    def load(self) -> "CostTracker":
        if self.path is None or not self.path.exists():
            return self
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.lifetime = Usage(
                calls=int(raw.get("calls", 0)),
                prompt_tokens=int(raw.get("prompt_tokens", 0)),
                output_tokens=int(raw.get("output_tokens", 0)),
                cost_usd=float(raw.get("cost_usd", 0.0)),
            )
        except (OSError, ValueError):
            pass  # a corrupt tally must not stop the assistant
        return self

    def _price(self) -> tuple[float, float]:
        for name, pair in self.prices.items():
            if name != "default" and self.model.startswith(name):
                return pair
        return self.prices.get("default", (0.30, 2.50))

    def record(self, usage: dict | None) -> float:
        """Add one call's usage. Returns the cost of that call in USD."""
        if not usage:
            return 0.0

        # Gemini reports promptTokenCount / candidatesTokenCount; accept the
        # obvious aliases so a different provider's shape still lands.
        prompt = int(
            usage.get("promptTokenCount")
            or usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or 0
        )
        output = int(
            usage.get("candidatesTokenCount")
            or usage.get("completion_tokens")
            or usage.get("output_tokens")
            or 0
        )

        in_price, out_price = self._price()
        cost = (prompt / 1_000_000) * in_price + (output / 1_000_000) * out_price

        for target in (self.session, self.lifetime):
            target.calls += 1
            target.prompt_tokens += prompt
            target.output_tokens += output
            target.cost_usd += cost
        return cost

    def save(self) -> None:
        if self.path is None:
            return
        payload = {
            "calls": self.lifetime.calls,
            "prompt_tokens": self.lifetime.prompt_tokens,
            "output_tokens": self.lifetime.output_tokens,
            "cost_usd": round(self.lifetime.cost_usd, 6),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=".cost-", suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def summary(self) -> str:
        s = self.session
        if s.calls == 0:
            return "no model calls this session"
        return (
            f"{s.calls} calls, {s.prompt_tokens:,} in / {s.output_tokens:,} out, "
            f"~${s.cost_usd:.4f} this session (lifetime ~${self.lifetime.cost_usd:.4f})"
        )
