"""The audit log.

A plain, append-only record of what JARVIS did and why: which tools ran, what the
heartbeat surfaced, what it held, and what it asked to confirm. When something
surprises you, this is how you find out what happened.

Deliberately a plain text file rather than a database — you should be able to
read it with `tail`, and grep it for a date.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path: Path, enabled: bool = True) -> None:
        self.path = path
        self.enabled = enabled

    def write(
        self,
        *,
        source: str,
        status: str,
        detail: str = "",
        extra: str = "",
    ) -> None:
        """Append one line. Never raises — logging must not break the assistant."""
        if not self.enabled:
            return
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        parts = [stamp, f"{source:<12}", f"{status:<9}"]
        if detail:
            parts.append(detail.replace("\n", " ")[:200])
        if extra:
            parts.append(f"({extra})")
        line = "  ".join(parts).rstrip() + "\n"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass

    def tail(self, lines: int = 40) -> list[str]:
        if not self.path.exists():
            return []
        try:
            content = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        return content[-lines:]
