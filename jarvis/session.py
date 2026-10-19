"""Session persistence — working memory that survives restarts.

Each turn is saved to a JSON file as it happens. On startup, the session
is recovered so "what we were just doing" survives a timeout or restart.

The active window is bounded to prevent unbounded growth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .providers import FunctionCall, Message, ToolOutput


@dataclass
class SessionStore:
    """Persist and recover conversation sessions."""

    path: Path
    max_messages: int = 50

    def save(self, messages: list[Message]) -> None:
        """Save the current session to disk."""
        data = {
            "saved_at": datetime.now().astimezone().isoformat(),
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "calls": [{"name": c.name, "args": c.args} for c in (m.calls or [])],
                    "outputs": [
                        {"name": o.name, "content": o.content, "ok": o.ok}
                        for o in (m.outputs or [])
                    ],
                    "raw": m.raw,
                }
                for m in messages[-self.max_messages:]
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def load(self) -> list[Message]:
        """Load the last session from disk."""
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        messages: list[Message] = []
        for raw in data.get("messages", []):
            role = raw.get("role", "user")
            content = raw.get("content", "")
            calls = [
                FunctionCall(name=c["name"], args=c["args"])
                for c in raw.get("calls", [])
            ]
            outputs = [
                ToolOutput(name=o["name"], content=o["content"], ok=o["ok"])
                for o in raw.get("outputs", [])
            ]
            messages.append(Message(
                role=role,
                content=content,
                calls=calls or None,
                outputs=outputs or None,
                raw=raw.get("raw"),
            ))

        # Skip leading non-user messages — Gemini requires the first message
        # to be from the user. A session saved mid-tool-exchange may start
        # with tool or assistant messages, which breaks the API on restore.
        while messages and messages[0].role != "user":
            messages.pop(0)

        return messages[-self.max_messages:]

    def clear(self) -> None:
        """Delete the saved session."""
        self.path.unlink(missing_ok=True)
