"""Time and date.

Safe to run on its own: read-only, no side effects, no network.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .base import Tool, ToolError

_PARAMS = {
    "type": "OBJECT",
    "properties": {
        "timezone": {
            "type": "STRING",
            "description": (
                "IANA timezone name such as 'Africa/Lagos' or 'Europe/London'. "
                "Omit to use the system's local time."
            ),
        }
    },
}


def get_current_time(timezone: str | None = None) -> str:
    if timezone:
        try:
            tz = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ToolError(
                f"'{timezone}' is not a timezone I recognise. Use an IANA name "
                "like 'Africa/Lagos' or 'America/New_York'."
            ) from exc
        now = datetime.now(tz)
        label = timezone
    else:
        now = datetime.now().astimezone()
        label = str(now.tzinfo)

    return (
        f"{now.strftime('%A, %d %B %Y, %H:%M')} ({label}). "
        f"UTC offset {now.strftime('%z')}."
    )


def build() -> list[Tool]:
    return [
        Tool(
            name="get_current_time",
            description=(
                "Use this to find the current date and time. Call it whenever the "
                "user asks what time or day it is, or when you need to know today's "
                "date to answer a question."
            ),
            parameters=_PARAMS,
            func=get_current_time,
        )
    ]
